# Migracion animal con Movebank

Aplicacion local de un usuario para explorar estudios accesibles, descargar posiciones GPS y analizar sus trayectorias. La unica fuente de datos de seguimiento es la API real de Movebank. La descarga y el uso de los datos estan sujetos a los [terminos de Movebank](https://www.movebank.org/cms/movebank-content/general-movebank-terms-of-use), su [politica de datos](https://www.movebank.org/cms/movebank-content/data-policy) y la licencia de cada estudio; revise tambien sus [recomendaciones de cita](https://www.movebank.org/cms/movebank-content/citation-guidelines).

## Arquitectura

```text
movebank_migracion/
  src/movebank/
    domain/
      models.py              modelos Pydantic
      event_normalization.py normalizacion de filas CSV antes del analisis
      analytics.py           mediciones de movilidad
      spatial.py             envolvente convexa y limites GeoJSON
    infrastructure/
      http/                  transporte HTTP generico
        client.py            solicitudes y sesiones reutilizables
        response.py          metadatos y contenido de respuesta
        exceptions.py        errores genericos de transporte HTTP
      movebank/
        client.py            autenticacion, licencias y CSV de Movebank
        consent.py           flujo de consentimiento desacoplado de la interfaz
        services.py          servicios de estudios, individuos y eventos
      persistence/store.py   almacenamiento SQLite con SQLAlchemy
    application/
      ports.py               contratos de sincronizacion
      sync.py                casos de uso de sincronizacion
      cli.py                 script de carga
    presentation/
      streamlit/app.py       interfaz y mapas
  tests/                     pruebas unitarias con respuestas controladas
  Dockerfile
  docker-compose.yml
  pyproject.toml
```

El dominio no depende de la interfaz, el cliente ni la base de datos. Los casos de uso coordinan servicios y persistencia mediante contratos; la configuracion de infraestructura conecta las implementaciones concretas. Se elige **SQLite** frente a DuckDB: es suficiente para sincronizar registros por individuo, permite transacciones y claves primarias, no requiere servidor y SQLAlchemy lo soporta directamente. DuckDB seria una evolucion adecuada para consultas analiticas masivas sobre Parquet, pero aqui no compensa mantener dos almacenes. La API REST propia, colas, procesamiento distribuido y permisos multiusuario quedan fuera de esta primera version: no exponer Streamlit a redes no confiables.

### Transporte HTTP y cliente Movebank

`HttpClient` es el transporte generico basado en `requests.Session`. Admite GET, POST, PUT, PATCH, DELETE y solicitudes genericas. Para estados HTTP inferiores a 400 devuelve un `HttpResponse` con metodo, URL, estado, cabeceras, duracion, tipo de contenido, texto y bytes; para estados de 400 o superiores lanza `HttpStatusError`, que conserva ese `HttpResponse`. Tambien distingue errores de conexion, timeout y transporte. El parsing JSON se realiza bajo demanda mediante `HttpResponse.json()`, que puede lanzar un error de interpretacion. `HttpClient` no interpreta respuestas de Movebank ni conoce sus endpoints o licencias. Sus mensajes de logging propios no incorporan cabeceras ni cuerpos de solicitud; esto no es un mecanismo global de sanitizacion de logs.

`MovebankClient` compone `HttpClient` y conserva las responsabilidades especificas de Movebank: autenticacion Basic cuando se proporcionan credenciales, parametros de `direct-read`, control de frecuencia, licencias, MD5, excepciones Movebank y validacion CSV. Crea y configura una unica sesion `requests.Session`, y entrega esa misma sesion a `HttpClient`; el transporte respeta los adaptadores ya configurados. `MovebankClient.close()` cierra la sesion compartida. `HttpClient.close()` cierra la sesion que tiene asignada, tambien si fue inyectada externamente; no hay una proteccion especifica frente a llamadas repetidas a `close()`.

Los errores genericos de transporte se convierten en `MovebankError` y conservan la causa encadenada. Los errores HTTP mantienen tambien el codigo de estado y el objeto de respuesta. `LicenseRequired` sigue siendo una excepcion especifica de Movebank y no se convierte en un error generico.

Cuando la respuesta incluye `License Terms:`, `MovebankClient` conserva los bytes originales y calcula sobre ellos el MD5 requerido por el protocolo al crear `LicenseRequired`. El hash esta disponible antes de solicitar la decision del usuario. Los flujos de CLI y Streamlit muestran los terminos y solicitan confirmacion; `MovebankClient` no puede acreditar por si mismo una autorizacion humana, solo verifica que el `approved_md5` recibido coincide con el esperado. Si coincide, envia una segunda solicitud con `license-md5` usando la misma sesion. No hay aceptacion automatica: sin ese MD5 coincidente no se envia la solicitud posterior. Las respuestas CSV se decodifican con `utf-8-sig` para admitir BOM; se validan las cabeceras requeridas y las filas malformadas.

`run_with_consent()` coordina una operacion y delega la decision en un callback, sin usar `input()` ni `print()` en el mecanismo compartido. El adaptador de CLI conserva la pregunta `ACEPTO`, sus mensajes y su salida por `SystemExit`; otra interfaz puede presentar los mismos terminos con su propia interaccion. Los MD5 aceptados se conservan solo durante esa operacion, nunca entre llamadas. Si una licencia distinta aparece durante el reintento, se solicita otra decision; si se repite el mismo MD5, el error se propaga para evitar un bucle.

### Normalizacion de eventos para analisis

`normalize_events()` prepara las filas CSV de eventos antes de pasarlas a `segments()`, `mobility()`, `daily_distance()` o las funciones espaciales. Devuelve todos los eventos normalizados, incluidos los de visibilidad desconocida, y contadores de aceptacion y rechazo. `hidden_count` cuenta los eventos validados con `visible=False`; `unknown_visibility_count` cuenta los que tienen visibilidad desconocida, y `unknown_visibility_events` permite consultarlos por separado. Para obtener los eventos aptos para analisis, use `events_for_analysis()`: por defecto incluye solo `visible=True`; `visible=False` y `visible=None` quedan excluidos. La inclusion de los desconocidos requiere solicitarla expresamente con `events_for_analysis(include_unknown_visibility=True)`. Ninguna de estas vistas elimina ni modifica los eventos conservados en `events`.

La visibilidad admite booleanos, cadenas sin distincion de mayusculas/minusculas `true`/`false` y valores numericos o cadenas `1`/`0`. Valores vacios, `None` y valores ausentes de pandas como NaN o `pd.NA` se conservan como `None`; valores no vacios desconocidos se rechazan, no se convierten a `True`. Cada fila rechazada se cuenta una sola vez. Los valores de visibilidad y las coordenadas ausentes o invalidas se clasifican durante la normalizacion; para los errores de validacion de `Event`, la prioridad es timestamp, coordenadas y otros errores, en ese orden. Las coordenadas numericas se convierten a `float` y el modelo `Event` valida sus rangos. La normalizacion no imprime ni registra filas.

En los campos opcionales de texto `individual_local_identifier` e `individual_taxon_canonical_name`, `None`, las cadenas vacias o blancas y los marcadores tipados de ausencia (`pandas.NA`, `pandas.NaT`, `numpy.nan` y `numpy.datetime64("NaT")`) se normalizan a `None`. Las cadenas literales `"NaN"` y `"NaT"` se conservan como texto.

Para las coordenadas, las entradas vacias y los marcadores tipados de ausencia se clasifican como `missing_coordinates`. Las cadenas literales `"NaN"` y `"NaT"`, el texto no numerico, los infinitos y los valores fuera de rango se clasifican como `invalid_coordinates`. El `timestamp` es obligatorio: los valores ausentes o invalidos se clasifican como `invalid_timestamp`; `pandas.NaT` no es un timestamp valido.

Los eventos deben quedar asociados a un `individual_id` valido. Cuando la consulta esta acotada a un individuo, `MovebankEventService` completa un identificador ausente o en blanco con el de esa consulta; no asigna identificadores arbitrarios. Los identificadores malformados o incompatibles con la consulta se rechazan. `normalize_events()` tambien rechaza eventos sin identificador, y `mobility()` y `segments()` excluyen defensivamente filas sin `individual_id`.

Las rutas de validacion no son identicas: el modelo `Event` valida campos y restricciones; `normalize_events()` ademas prepara las entradas y clasifica las filas rechazadas. El notebook llama a `normalize_events()` y puede informar esas categorias. CLI y Streamlit guardan mediante `Store.save_events()`, que valida los eventos con `Event` y omite coordenadas ausentes; no presentan necesariamente las mismas categorias de rechazo que el notebook. Streamlit aplica ademas `events_for_analysis()` y excluye la visibilidad desconocida por defecto.

Las claves internas de Movebank pueden cambiar y los identificadores locales solo son unicos dentro de un estudio. La caché usa IDs internos para consultar y guardar snapshots, conserva identificadores locales y debe actualizarse si se recrean entidades. Cada descarga sustituye atomicamente los eventos del individuo; incluso una descarga vacia queda marcada como completa. La caché no detecta cambios remotos: use actualizacion explicita. Los archivos SQLite contienen potencialmente datos privados sin cifrar; proteja su acceso y no los comparta.

## Instalacion y uso local

Requiere Python 3.12 o posterior.

Copie `.env.example` como `.env` en esta carpeta y complete las variables que aparecen en la plantilla: `MOVEBANK_USERNAME` y `MOVEBANK_PASSWORD`. `.env.example` es una plantilla con valores vacios, no contiene credenciales reales. El archivo `.env` contiene la contrasena **sin cifrar**: proteja el acceso local y no lo comparta ni lo incluya en la entrega. Esta excluido de Git y de la imagen Docker.

```dotenv
MOVEBANK_USERNAME='su_usuario'
MOVEBANK_PASSWORD='su_contrasena'
```

Use comillas simples para valores con caracteres especiales; una comilla simple dentro del valor se escribe como `\'`.

```powershell
cd movebank_migracion
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\movebank-load.exe studies
.\.venv\Scripts\movebank-load.exe individuals --study 2911040
.\.venv\Scripts\movebank-load.exe events --study 2911040 --individual ID_INDIVIDUO
.\.venv\Scripts\streamlit.exe run src\movebank\presentation\streamlit\app.py
```

`credentials()` localiza el `.env` de la raiz de este subproyecto independientemente del directorio de trabajo; tambien admite una ruta explicita. Las variables de entorno existentes tienen prioridad sobre los valores del archivo, por credencial. Despues de cambiar las credenciales, reinicie el dashboard y cierre las sesiones anteriores del navegador. Si ambas estan vacias, se intenta el acceso anonimo documentado; algunas instalaciones o respuestas pueden exigir autenticacion. Utilice su propia cuenta y permisos. Nunca incluya contrasenas en el codigo ni en el repositorio. La ruta SQLite predeterminada sigue dependiendo del directorio desde el que se inicie la CLI o el dashboard; `--database` permite seleccionar otra ruta para la CLI. Para refrescar eventos mediante CLI use `--refresh`. Desde el dashboard, «Descargar o actualizar GPS» siempre refresca.

### Navegacion por Streamlit

En la barra lateral, actualice los estudios, seleccione un estudio y actualice sus individuos; despues seleccione un individuo y descargue o actualice sus eventos GPS. La descarga desde el dashboard siempre refresca los eventos. Las paginas disponibles son:

- **Resumen:** muestra individuos, especies, posiciones, distancia y la envolvente convexa.
- **Estudios:** permite filtrar localmente por taxon, sensor y ano de seguimiento. El ano debe tener cuatro digitos y requiere fechas de seguimiento disponibles.
- **Individuos:** muestra la lista del estudio y los detalles del individuo seleccionado.
- **Mapa:** presenta trayectorias, posiciones, mapa de calor y agrupaciones visuales de marcadores.
- **Analitica:** presenta distancias diarias, recuentos por mes, ano e individuo, y permite consultar regiones con un GeoJSON local.

El intervalo maximo entre posiciones y el umbral de velocidad para detenido/en movimiento se configuran en la barra lateral. Si no hay estudios, la interfaz solicita actualizar el catalogo. Mapa y Analitica muestran el aviso de descargar posiciones cuando no quedan eventos visibles para analizar, incluso si hay filas ocultas o de visibilidad desconocida almacenadas. La visibilidad desconocida se excluye del analisis por defecto; esta interfaz no ofrece una opcion para incluirla. Los filtros de estudios usan los campos que devuelve Movebank, por lo que un filtro por ano no funciona si faltan las fechas de seguimiento. Una ruta GeoJSON inaccesible o entidades sin los campos seleccionados se comunica como error.

## Notebook de consulta

Abra [consulta_movebank.ipynb](consulta_movebank.ipynb) en VS Code y seleccione el kernel de `.venv`. Si no tiene soporte de notebooks en ese entorno, instale `.\.venv\Scripts\python.exe -m pip install -e ".[notebook]"`. Al ejecutar las celdas de consulta, el notebook solicita datos a Movebank; la tabla presenta todos los estudios recibidos, permite ordenar localmente por el numero de individuos cuando esta disponible y muestra los valores ausentes como no disponibles. Se puede seleccionar cualquier estudio por su identificador: no se descartan automaticamente estudios pequenos ni se consulta de nuevo al ordenar. El numero de individuos es solo un indicador inicial; evalua tambien el numero de eventos GPS, la duracion del seguimiento, la frecuencia de muestreo, la continuidad y la calidad de las coordenadas. Los resultados del notebook se mantienen ahi y no se cargan automaticamente en la cache del dashboard. Antes de compartirlo, borra sus salidas si contienen datos cuyo acceso o redistribucion este restringido.

Los flujos de CLI, Streamlit y el notebook muestran el contenido de la licencia y solicitan confirmacion antes de volver a llamar con el MD5 coincidente. Si los terminos cambian, se solicita una nueva aceptacion. El MD5 es un requisito del protocolo, no una garantia criptografica, y las aceptaciones no se almacenan para uso futuro. La sesion compartida permite reutilizar las cookies administradas por `requests.Session`.

La API limita a **una solicitud concurrente por IP** y 20 globalmente. `MovebankClient` serializa las llamadas dentro de su proceso y espera un segundo entre ellas. Su adaptador conserva la politica historica de reintentos:

```python
Retry(
    total=3,
    connect=None,
    read=None,
    status=None,
    other=None,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
    raise_on_status=False,
)
```

Los campos `connect`, `read`, `status` y `other` quedan en `None` en la configuracion efectiva; el contador global `total` limita los reintentos. Los reintentos por estado HTTP se limitan a GET mediante `allowed_methods`. Los errores de conexion siguen otra ruta: pueden consumir el presupuesto global incluso para otros metodos HTTP. La integracion actual de Movebank envia consultas GET. `raise_on_status=False` permite que la respuesta HTTP final llegue a `HttpClient` para su tratamiento y diagnostico. Si `HttpClient` crea su propia sesion, usa sus adaptadores predeterminados; si recibe una sesion externa, conserva sus adaptadores y la politica de reintentos ya configurada. No coordina varios procesos o maquinas que compartan IP: ejecute una sola instancia y evite otros clientes simultaneos. El limite de frecuencia exacto no es una garantia de Movebank.

## Docker

Con el archivo `.env` configurado, ejecute `docker compose up --build` desde esta carpeta. Docker Compose lee las credenciales del archivo y las pasa como variables al contenedor. Visite `http://localhost:8501`. Los datos se guardan en `data/`; para los limites GeoJSON, coloque el archivo alli y use su ruta en el contenedor, por ejemplo `/data/limites.geojson`. El puerto solo se publica en localhost; el dashboard no implementa autenticacion propia. No utilice este despliegue para multiples usuarios.

## Datos y criterios analiticos

- Se descargan GPS (`sensor_type_id=653`) por estudio e individuo, con `event_id`, identificadores, taxon y `visible`. Se omiten registros sin coordenadas; valores invalidos provocan error. Los eventos marcados `visible=false` y los de visibilidad desconocida (`visible=None`) se conservan en almacenamiento, pero se excluyen del analisis por defecto. El notebook permite incluir los desconocidos solo tras una decision explicita; los eventos `visible=false` nunca se incluyen.
- Distancia: suma de geodesicas WGS84 entre posiciones consecutivas del mismo individuo. Velocidad media: distancia total dividida por tiempo entre posiciones admitidas; maxima: maxima velocidad de segmento. Distancia media: media por segmento. Dos posiciones con igual fecha no forman segmento. Intervalos superiores al maximo configurable se excluyen; distancia diaria se atribuye al dia UTC de la posicion final. Se trata de estimaciones, no de distancia real continua.
- Detenido/en movimiento: suma de intervalos cuya velocidad de segmento es inferior/superior o igual al umbral configurable. No equivale a comportamiento observado. La duracion es el intervalo UTC entre primera y ultima posicion valida del conjunto, no la suma de tiempos de seguimiento.
- Area: envolvente convexa de todas las posiciones seleccionadas, proyectada a Lambert azimutal equivalente local; no es una estimacion de area de campeo por KDE. La densidad es posiciones por km² de dicha envolvente. No se calcula para trayectorias que cruzan el antimeridiano. Menos de tres posiciones no producen area.
- Actividad significa numero de posiciones, condicionada por la frecuencia de muestreo. Las estaciones son meteorologicas del hemisferio norte. Las comparaciones no corrigen diferencias de esfuerzo.
- Paises y regiones requieren un GeoJSON FeatureCollection en WGS84, aportado por el usuario, con los dos campos configurados en todas sus entidades. Se cuentan unicamente poligonos que cubren posiciones observadas; no se infieren cruces entre ellas. Los puntos en el mar pueden no pertenecer a ningun poligono. Seleccione datos de limites y licencias apropiados; no se descarga ningun dataset externo. La capa de mapa base de Folium puede solicitar teselas a su proveedor, que recibe la IP del cliente.

Los estudios se filtran por taxon, sensor y ano comprendido entre las fechas de seguimiento conocidas. La lista se obtiene con `i_have_download_access=true`: si hay autenticacion puede incluir estudios privados accesibles, no solamente publicos. Sin autenticacion el acceso se limita a lo publico segun la documentacion. Las fechas y taxones incompletos pueden excluir estudios relevantes.

## Pruebas y calidad

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m black --check src tests
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src
```

Como referencias historicas, no como resultados actuales, la validacion de integracion HTTP de la FASE 4 registro **64 pruebas** y **90,65 % de cobertura global**, y la verificacion de la FASE 5.9 registro **88 pruebas** y **93,39 % de cobertura**. El umbral configurado es **80 %**. Las pruebas de transporte e integracion usan respuestas simuladas; durante la verificacion de la FASE 5.9 se bloquearon las conexiones externas y SQLite solo se utilizo en rutas temporales aisladas. El notebook no se ejecuto ni se hicieron consultas reales a Movebank durante esa verificacion.

Las pruebas controladas no sustituyen una integracion real autenticada. Para verificarla, use una cuenta propia y un estudio cuyo uso este autorizado; contraste el CSV, los permisos, los terminos y las cifras con Movebank. No se incluyen credenciales ni datos de terceros.

## Roadmap

1. **Robustez y produccion:** prueba de integracion autenticada, aislamiento multiusuario y control de acceso, sincronizacion incremental incluyendo eliminaciones, streaming y limites de volumen, observabilidad, control de concurrencia distribuido por IP y migraciones de esquema. Solo despues desplegar en un servidor compartido.
2. **GIS:** capas versionadas y licenciadas, indice espacial, tratamiento del antimeridiano, modelos KDE y evaluacion de incertidumbre de GPS y huecos.
3. **Clustering espacial:** modulo DBSCAN con distancia haversine, coordenadas en radianes y `eps` en metros convertido al radio terrestre; agrupar por individuo y validar duracion y muestreo antes de etiquetar zonas de descanso.
4. **Eventos migratorios:** detector configurable por especie basado en distancia, direccion y persistencia; distinguir paradas prolongadas de huecos de muestreo y validar con datos etiquetados. No presentar umbrales arbitrarios como observaciones biologicas.
5. **Prediccion:** evaluar XGBoost frente a un baseline de ultima posicion usando particiones temporales y por individuo; medir error geodesico por horizonte y evitar fuga temporal. Prophet modela series temporales, no ubicaciones geograficas directamente, por lo que requiere modelar coordenadas por separado y evaluar el cruce del antimeridiano. Ninguno se ofrece hasta disponer de validacion.
6. **API propia:** definir contratos, autenticacion, autorizacion por estudio, paginacion y limites; reutilizar los casos de uso sin publicar datos sujetos a licencias.

Fuente tecnica: [documentacion oficial de la API de Movebank](https://github.com/movebank/movebank-api-doc/blob/master/movebank-api.md), incluidos los apartados de licencias, atributos, entidades, sensores y limites.
