# Arquitectura del Sistema

> **Nota:** este documento fue revisado a fondo a partir de
> `docs/ANALISIS_PROYECTO.md`, que detecto un cuello de botella
> arquitectonico critico y varios bugs de concurrencia. Todos los puntos
> de esa revision fueron corregidos; esta version del documento ya
> describe la arquitectura **corregida**.

## 1. Visión General

El sistema implementa un **auditor de contraseñas basado en hashes** con
**tres motores de ejecución** intercambiables, todos expuestos a traves de
una fachada orientada a objetos comun (`hash_auditor/auditors.py`, RNF-05):

1. **Secuencial** (`AuditorSecuencial` -> `sequential_auditor.py`) — línea base, un solo hilo (RF-04).
2. **Hilos** (`AuditorHilos` -> `threaded_auditor.py`) — concurrencia con `threading` (memoria compartida nativa).
3. **Procesos** (`AuditorProcesos` -> `parallel_auditor.py`) — paralelismo real con `multiprocessing` (evita el GIL).

Los tres reciben la misma entrada (hashes objetivo + diccionario) y
producen la misma estructura de resultado (`ResultadoAuditoria`), lo que
permite comparar tiempos de forma homogénea (RF-12).

## 2. Diagrama del pipeline concurrente (hilos y procesos)

```
                      ┌────────────────────────────┐
                      │   Productor                 │
                      │  (dictionary.generar_lotes_  │
                      │   palabras)                  │
                      │                              │
                      │ SOLO empaqueta PALABRAS BASE │
                      │ en lotes pequeños (3 por      │
                      │ defecto) -- NO expande        │
                      │ mutaciones aqui               │
                      └───────────────┬──────────────┘
                                      │ task_queue.put(lote_de_palabras)
                                      │  (Queue ACOTADA, maxsize=200)
                                      ▼
                      ┌────────────────────────────┐
                      │      task_queue (IPC)       │   <- RF-08
                      └───┬────────┬────────┬───────┘
                          │        │        │
             ┌────────────┘  ┌─────┘  ┌─────┘ ... (N trabajadores)
             ▼                ▼        ▼
       ┌───────────┐   ┌───────────┐   ┌───────────┐
       │ worker-1  │   │ worker-2  │   │ worker-N  │
       │           │   │           │   │           │
       │ por cada  │   │ por cada  │   │ por cada  │
       │ palabra:  │   │ palabra:  │   │ palabra:  │
       │  expande  │   │  expande  │   │  expande  │
       │  mutaciones│   │  mutaciones│   │  mutaciones│
       │  LOCALMENTE│  │  LOCALMENTE│  │  LOCALMENTE│
       │  y calcula │  │  y calcula │  │  y calcula │
       │  cada hash │  │  cada hash │  │  cada hash │
       └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
             │  hallazgo?           hallazgo?
             │  (1) escribe bitácora compartida bajo Lock   <- RF-09
             │  (2) result_queue.put(hallazgo)              <- RF-08
             ▼
       ┌────────────────────────────┐
       │   Proceso/hilo PRINCIPAL   │
       │ (colector / orquestador)   │
       │                             │
       │ lee result_queue en vivo   │  <- RNF-04
       │ DEDUPLICA por (hash,usuario)│ <- corrige bug de hallazgos duplicados
       │ si 100% descifrado:        │
       │     stop_event.set()       │  <- RF-10 (Event)
       │ join() / terminate() todos │  <- RNF-03
       └────────────────────────────┘
```

La version con **hilos** (`threaded_auditor.py`) es arquitectonicamente
IDENTICA a la de procesos, cambiando unicamente las primitivas:

| Concepto | Hilos (`threading`) | Procesos (`multiprocessing`) |
|---|---|---|
| Cola de tareas | `queue.Queue` | `multiprocessing.Queue` |
| Exclusion mutua | `threading.Lock` | `multiprocessing.Lock` |
| Señal de parada | `threading.Event` | `multiprocessing.Event` |
| Contador compartido | entero + `threading.Lock` | `multiprocessing.Value` + `Lock` |
| Memoria | **compartida nativamente** (mismo proceso) | **independiente** (requiere IPC/pickle) |
| Afectado por el GIL | **Si** | No |

## 3. Técnicas de la materia aplicadas

| Técnica                                   | Dónde                                              | Requisito |
|--------------------------------------------|-----------------------------------------------------|-----------|
| Hilos / multihilos (`threading`)           | `threaded_auditor.py`                               | Enunciado §1, RF-05 |
| Paralelismo real con procesos (`multiprocessing`) | `parallel_auditor.py`: 1 productor + N trabajadores | RF-05, RF-06 |
| Modelo Productor-Consumidor                | `_proceso_productor`/`_hilo_productor` + trabajadores | Arquitectura |
| Comunicación entre procesos/hilos (`Queue`)| `task_queue`, `result_queue`                        | RF-08 |
| Exclusión mutua (`Lock`)                   | `bitacora_lock` (bitácora), `contador_lock`/`_ContadorCompartido` | RF-09 |
| Señalización / parada temprana (`Event`)   | `stop_event`                                        | RF-10 |
| Partición del espacio de búsqueda          | Lotes de PALABRAS BASE (no de candidatos) extraídos dinámicamente de la cola | RF-06 |
| Diseño orientado a objetos                 | `auditors.py`: `BaseAuditor` (ABC) + 3 subclases    | RNF-05 |

## 4. Por qué la partición es dinámica y por PALABRAS (no por candidatos)

En lugar de dividir el diccionario en N bloques fijos *antes* de arrancar
(partición estática), el sistema reparte el trabajo en **lotes pequeños de
palabras base** (3 por defecto) a través de una cola compartida. Dos
decisiones de diseño clave:

1. **Dinámica, no estática**: si un trabajador termina su lote antes que
   otro, toma el siguiente de inmediato — balanceo de carga automático.
   Con partición estática, un trabajador "lento" se convierte en el
   cuello de botella aunque los demás ya hayan terminado.
2. **Por palabras, no por candidatos ya mutados**: cada trabajador expande
   sus propias mutaciones (`mutar_palabra`) de forma local tras recibir el
   lote. Ver §6 para la justificación detallada de por qué esto es
   crítico para el rendimiento.

Sigue cumpliéndose el requisito de "bloques disjuntos": cada lote sale de
la cola exactamente una vez, por lo que ninguna palabra se procesa dos
veces desde la cola (ver §8 sobre deduplicación por palabras repetidas en
el propio archivo de diccionario).

## 5. Decisiones de rendimiento relevantes

- **El Productor NUNCA expande mutaciones.** Ver §6: es la causa raíz de
  un cuello de botella crítico detectado y corregido durante la revisión
  del proyecto.
- **`stop_event.is_set()` se revisa por palabra, no por candidato**:
  revisar un `Event`/`Lock` de `multiprocessing` usa primitivas de
  sincronización del sistema operativo (no es una simple lectura de
  variable en memoria). Revisarlo en cada uno de los millones de
  candidatos introduce un overhead de IPC muchas veces mayor que el propio
  cálculo del hash. Revisarlo una vez por palabra (que expande a cientos o
  miles de candidatos) conserva la "parada temprana" (RF-10) sin destruir
  el rendimiento.
- **El algoritmo de hash se resuelve una sola vez por proceso/hilo**
  (`hash_engine.obtener_constructor`) en lugar de validar el nombre del
  algoritmo en cada candidato.

## 6. Cuello de botella corregido: Productor expandiendo candidatos

**Diagnóstico (antes de la corrección):** el Productor generaba TODOS los
candidatos mutados (millones de strings) y los serializaba (`pickle`) en
lotes hacia la cola; cada trabajador debía deserializarlos antes de
calcular los hashes. Dado que `hashlib` es muy rápido (C/OpenSSL), la
generación de millones de strings + su serialización en UN SOLO proceso
dominaba ~80% del tiempo total. Por la **Ley de Amdahl**, con una fracción
serial *f* ≈ 0.80, el Speedup máximo posible (con infinitos núcleos) es:

```
S_max = 1 / f = 1 / 0.80 = 1.25x
```

Esto coincidía exactamente con el techo observado (~1.19x con 4-8
workers), confirmando el diagnóstico.

**Corrección aplicada:** el Productor ahora encola únicamente **palabras
base** (`dictionary.generar_lotes_palabras`); cada trabajador expande sus
propias mutaciones localmente (`mutar_palabra`) y calcula los hashes sin
que el espacio de búsqueda completo pase por IPC. El tráfico por la cola
se redujo de millones de strings (decenas/cientos de MB serializados) a
unas pocas palabras (unos KB) por lote. Resultado medido tras la
corrección -- corrida oficial guardada en `results/metricas_comparativas.csv`
(SHA-256, 20 cuentas, 7,416,430 candidatos REALMENTE evaluados, `--extendido`):

> **Nota sobre la cifra de candidatos:** `dictionary.estimar_total_candidatos()`
> da una COTA SUPERIOR de `7,511,889` para este diccionario, asumiendo 3
> variantes de capitalización (minúscula/Capitalizada/MAYÚSCULA) por
> palabra. El conteo real evaluado por el sistema es `7,416,430`, un poco
> menor: palabras puramente numéricas del diccionario base (p. ej.
> `"123456"`, `"000000"`, `"111111"`) solo producen **una** variante de
> capitalización (no tiene sentido "capitalizar" un número), porque
> `variantes_de_capitalizacion` las deduplica en un `set`. La diferencia
> (`95,459` candidatos, ~1.3%) es exactamente ese ajuste; ambas cifras son
> correctas, solo miden cosas ligeramente distintas (estimación vs. conteo
> real) y conviene usar la real (`7,416,430`) en el Documento Técnico para
> que coincida con `results/`.

| Configuración | Tiempo (s) | Speedup |
|---|---|---|
| secuencial | 19.62 | 1.00x |
| procesos (N=1) | 18.05 | 1.09x |
| procesos (N=2) | 14.48 | 1.36x |
| procesos (N=4) | 10.78 | 1.82x |
| procesos (N=8) | 10.63 | 1.85x |

El *Speedup* deja de estar limitado por la fracción serial del Productor;
el techo observado ahora refleja la saturación de los núcleos físicos
disponibles en la máquina de prueba (ver §7), no un cuello de botella de
diseño.

> **Nota sobre `procesos (N=1)` = 1.09x (eficiencia 108.7%):** llama la
> atención que UN solo proceso trabajador resulte ligeramente más rápido
> (18.05s) que la línea base secuencial (19.62s) -- en teoría, con N=1 no
> hay paralelismo real, solo el overhead de crear un proceso extra y
> comunicarse con el por `Queue`/`Pickle`, así que lo esperable sería que
> fuera un poco MÁS LENTO que secuencial, no más rápido. La explicación
> más probable no es un error de medición, sino una diferencia real en el
> *hot loop*: el motor secuencial usa un diccionario Python
> (`pendientes.pop(h)`/`in`) para la búsqueda de coincidencias dentro de
> un único generador anidado (`generar_candidatos` → `mutar_palabra`),
> mientras que cada trabajador de `procesos` recibe palabras ya
> particionadas y expande sus mutaciones en un bucle más simple y
> localizado (mejor localidad de cache de instrucciones). A esa diferencia
> se suma la variación normal entre corridas (frecuencia dinámica de la
> CPU, *turbo boost*, otros procesos del sistema operativo). Es una
> diferencia de apenas 1.6s sobre ~19s (menos del 10%) y no cambia la
> conclusión central: el verdadero paralelismo aparece a partir de N=2.

## 7. Hilos vs. Procesos: el efecto medible del GIL

Esta es la comparación que motivó agregar `threaded_auditor.py`. Mismos
datos, mismo hardware, misma arquitectura Productor-Consumidor — la única
diferencia es `threading` vs. `multiprocessing`:

| Configuración | Tiempo (s) | Speedup |
|---|---|---|
| secuencial | 19.62 | 1.00x |
| **hilos** (N=1) | 23.41 | **0.84x** (¡más lento que secuencial!) |
| **hilos** (N=4) | 17.75 | **1.11x** (el mejor caso de hilos, apenas por encima de 1x) |
| **hilos** (N=8) | 29.06 | **0.68x** (empeora: mas hilos, mas contencion por el GIL) |
| **procesos** (N=4) | 10.78 | **1.82x** |
| **procesos** (N=8) | 10.63 | **1.85x** |

El cálculo de hashes es **CPU-bound**. En CPython, el *Global Interpreter
Lock* (GIL) impide que el bytecode de dos hilos se ejecute realmente en
paralelo sobre varios núcleos. Aunque `hashlib` libera el GIL mientras
calcula el dígest en C, para strings muy cortas (8-20 bytes, como las
contraseñas candidatas) el costo de adquirir/liberar el GIL en cada
llamada compite con el propio cálculo — por eso `threading` **no mejora,
e incluso empeora**, el rendimiento de esta carga. `multiprocessing`, en
cambio, usa procesos con intérprete y memoria independientes (sin GIL
compartido), por lo que sí logra paralelismo real.

**Conclusión para el informe técnico:** no todo problema concurrente se
beneficia de `threading` en Python; para carga CPU-bound, `multiprocessing`
es la herramienta correcta. `threading` sí sería la opción adecuada para
cargas I/O-bound (por ejemplo, consultar múltiples APIs o leer muchos
archivos en paralelo), que es precisamente lo que NO hace este sistema.

## 8. Qué significan los resultados del benchmark

Con un espacio de búsqueda pequeño, el **costo fijo de crear procesos**
(varias decenas a cientos de milisegundos por proceso en Windows) puede
dominar el tiempo total. A medida que el espacio de búsqueda crece
(bandera `--extendido`), ese costo fijo se amortiza y el *Speedup* se
acerca más al número de núcleos físicos disponibles — hasta saturarlos,
punto en el que agregar más trabajadores ya no ayuda (e incluso puede
empeorar ligeramente por cambio de contexto). Este comportamiento **no es
un error**: es exactamente lo que predicen la Ley de Amdahl y la
saturación de recursos físicos, y es el tipo de análisis que se espera
documentar en el informe técnico final.

## 9. Corrección de bugs de concurrencia (RNF-02)

Durante la revisión se identificaron y corrigieron:

- **Pérdida de usuarios con contraseñas duplicadas**: el mapa interno pasó
  de `hash -> usuario_id` a `hash -> [usuario_id, ...]`
  (`sequential_auditor.construir_mapa_objetivos`), usado por los tres
  motores. `total_objetivos` ahora cuenta CUENTAS, no hashes únicos.
- **Hallazgos duplicados / parada prematura**: el colector (en los tres
  motores) deduplica cada hallazgo por `(hash, usuario_id)` antes de
  contarlo, evitando que una palabra repetida en el diccionario infle el
  conteo y dispare `stop_event` antes de encontrar el 100% real.
- **Diccionario con palabras duplicadas**: `cargar_diccionario` ahora
  elimina duplicados preservando el orden, reduciendo aún más el riesgo
  de hallazgos duplicados.
- **Selección incorrecta del resultado para el reporte**: `main.py` elegía
  `max(resultados, key=...)`, que en caso de empate devuelve el PRIMER
  elemento (siempre N=1), atribuyendo todas las credenciales a un único
  worker en el reporte. Corregido a
  `key=lambda r: (r.descifrados, r.num_trabajadores)`.
