# Auditor y Descifrador Concurrente de Contraseñas / Hashes

**Proyecto Final — Programación Paralela y Concurrente**

Herramienta de auditoría de seguridad que evalúa la robustez de contraseñas
almacenadas como hashes (MD5, SHA-256, SHA-512) mediante un ataque de
diccionario híbrido (diccionario base + mutaciones de mayúsculas, sufijos
numéricos y símbolos), comparando **tres motores de ejecución**:
secuencial, concurrente con **hilos** (`threading`) y paralelo con
**procesos** (`multiprocessing`) — con métricas de desempeño (Speedup,
Eficiencia, Throughput) y gráficas SVG listas para el informe.

> **Uso previsto:** auditoría educativa/defensiva sobre hashes generados por
> el propio sistema (`generate-dataset`), o sobre un archivo CSV/TXT de
> hashes que el equipo controla. No está pensado ni debe usarse contra
> credenciales de terceros sin autorización.

Desarrollado **100% con bibliotecas estándar de Python** (`hashlib`,
`multiprocessing`, `threading`, `queue`, `time`, `csv`, `argparse`,
`random`, `unittest`) — sin dependencias externas (RNF-01).

> **Revisión técnica:** este proyecto fue auditado a fondo contra la
> rúbrica del profesor y se corrigieron todos los hallazgos — ver
> [docs/ANALISIS_PROYECTO.md](docs/ANALISIS_PROYECTO.md) (diagnóstico
> original) y [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) §6-9
> (correcciones aplicadas: cuello de botella del Productor, bugs de
> concurrencia, y el contraste Hilos vs. Procesos frente al GIL).

---

## 1. Estructura del proyecto

```
Proyecto/
├── main.py                        # CLI principal (generate-dataset / audit / benchmark)
├── hash_auditor/
│   ├── hash_engine.py              # Motor multi-algoritmo + autodeteccion (RF-07)
│   ├── dictionary.py               # Diccionario base + motor de mutaciones (RF-03)
│   ├── dataset_generator.py        # Datasets sinteticos + carga CSV/TXT (RF-01, RF-02)
│   ├── sequential_auditor.py       # Auditor secuencial (linea base) (RF-04)
│   ├── threaded_auditor.py         # Auditor concurrente con `threading`
│   ├── parallel_auditor.py         # Auditor paralelo con `multiprocessing`: Queue/Lock/Event
│   ├── auditors.py                 # Fachada POO: BaseAuditor + 3 subclases (RNF-05)
│   ├── metrics.py                  # Speedup, eficiencia, throughput (RF-11, RF-12)
│   ├── charts.py                   # Graficas SVG sin dependencias externas
│   └── report_generator.py         # Reporte de vulnerabilidad (RF-13)
├── tests/                          # Suite de pruebas automatizadas (unittest)
├── data/
│   ├── diccionario_base.txt        # ~340 contraseñas/palabras comunes
│   └── hashes_objetivo.csv         # Dataset de ejemplo ya generado
├── results/                        # Salidas: reportes, metricas, bitacoras, graficas/
└── docs/
    ├── ARQUITECTURA.md             # Diagrama, justificacion de diseño y analisis Amdahl/GIL
    └── ANALISIS_PROYECTO.md        # Auditoria tecnica que origino las correcciones
```

## 2. Requisitos

- Python 3.10+ (probado con Python 3.14 en Windows 11).
- Sin dependencias de terceros — no se necesita `pip install` nada.

## 3. Cómo ejecutarlo (PowerShell, desde la carpeta del proyecto)

### 3.1 Generar un dataset sintético de auditoría (RF-02)

```powershell
python main.py generate-dataset --n 20 --algoritmo sha256
```

Genera `data/hashes_objetivo.csv` (lo único que "recibe" el sistema, RF-01)
y `results/referencia_verificacion.csv` (contraseñas en claro + nivel de
complejidad, **solo para que el equipo valide los resultados**; el motor de
auditoría nunca lee este archivo).

También se puede usar un archivo `.txt` plano (una linea por hash, con o
sin `usuario_id:` al inicio) — el algoritmo se **autodetecta** por la
longitud del hash (RF-07):

```
usuario_juan:5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d
8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92
```

### 3.2 Auditoría rápida (demo en vivo, modo normal)

```powershell
python main.py audit --modo procesos --workers 4 --objetivos data\hashes_objetivo.csv --algoritmo sha256
```

En modo normal (sin `--extendido`) el espacio de búsqueda es pequeño
(~150 mil candidatos) y la auditoría termina en 1-2 segundos — ideal para
mostrar en vivo durante la presentación oral. Cambiar `--modo procesos`
por `--modo hilos` ejecuta exactamente la misma arquitectura pero con
`threading` en lugar de `multiprocessing` — útil para comparar.

### 3.3 Auditoría exhaustiva (`--extendido`)

```powershell
python main.py audit --modo procesos --workers 4 --objetivos data\hashes_objetivo.csv --algoritmo sha256 --extendido
```

Activa sufijos numéricos de hasta 3-4 dígitos y años (1990-2029): varios
millones de candidatos. Recupera también las contraseñas de complejidad
"media" que el modo normal no alcanza a cubrir.

### 3.4 Benchmark comparativo completo (secuencial + hilos + procesos, 1/2/4/8)

```powershell
python main.py benchmark --algoritmo sha256 --objetivos data\hashes_objetivo.csv --extendido --workers 1 2 4 8
```

Ejecuta la línea base secuencial, luego **hilos** (1,2,4,8) y luego
**procesos** (1,2,4,8), calcula la tabla comparativa completa
(Speedup/Eficiencia/Throughput) e imprime en consola una comparación
explícita del efecto del GIL. Genera:

- `results/reporte_vulnerabilidad.md` — reporte de vulnerabilidades (RF-13).
- `results/metricas_comparativas.csv` — tabla de métricas en CSV.
- `results/hallazgos_detalle.csv` — detalle de credenciales recuperadas.
- `results/graficas/*.svg` — gráficas de Speedup, Eficiencia y Tiempo listas para el informe/presentación.
- `results/bitacora_<modo>_w<N>.log` — bitácora compartida de cada corrida.

Agregar `--sin-hilos` omite las corridas de `threading` (solo secuencial + procesos, más rápido de ejecutar).

> Nota: con `--extendido` el benchmark completo puede tardar uno o dos
> minutos según el hardware, ya que evalúa el espacio de búsqueda ampliado
> en 9 configuraciones distintas. Es la corrida "oficial" que se
> recomienda incluir en el documento técnico y capturar para la
> presentación.

### 3.5 Ejecutar la suite de pruebas automatizadas

```powershell
python -m unittest discover -s tests -v
```

Incluye pruebas de: motor de hashes (los 3 algoritmos), reproducibilidad
por `seed`, equivalencia de resultados entre los 3 motores, parada
temprana (RF-10 — verifica que el `Event` detenga a los trabajadores
mucho antes de agotar el espacio de búsqueda) e integridad concurrente
(RNF-02 — ningún hallazgo se pierde, incluso con contraseñas duplicadas
entre usuarios o corriendo la misma auditoría varias veces).

## 4. Interpretación de resultados

Ver `docs/ARQUITECTURA.md` §6-8 para el análisis completo de por qué el
*Speedup* no crece linealmente con el número de trabajadores, y por qué
**hilos** (`threading`) prácticamente no mejora el tiempo frente a
secuencial mientras que **procesos** (`multiprocessing`) sí lo hace de
forma clara — es el efecto directo del *Global Interpreter Lock* (GIL) de
Python sobre cargas CPU-bound, y es exactamente el análisis que se espera
documentar en el informe técnico.

Las contraseñas de nivel "fuerte" (aleatorias, 16 caracteres) **no se
recuperan nunca**: están deliberadamente fuera del espacio de búsqueda del
diccionario, para demostrar de forma responsable que la longitud/aleatoriedad
real sigue siendo la mejor defensa frente a un ataque de diccionario.

## 5. Mapeo de requisitos funcionales

| Requisito | Dónde se implementa |
|-----------|----------------------|
| RF-01 Carga de hashes objetivo (CSV o TXT) | `dataset_generator.cargar_objetivos` |
| RF-02 Generador de escenarios sintéticos | `dataset_generator.generar_dataset` |
| RF-03 Diccionario + motor de mutaciones | `dictionary.py` |
| RF-04 Modo secuencial (baseline) | `sequential_auditor.py` / `AuditorSecuencial` |
| RF-05 Modo concurrente escalable (1/2/4/8) | `threaded_auditor.py` + `parallel_auditor.py` |
| RF-06 Partición del espacio de búsqueda | `dictionary.generar_lotes_palabras` + cola compartida |
| RF-07 Multi-algoritmo + autodetección | `hash_engine.py` (`detectar_algoritmo_por_longitud`) |
| RF-08 Comunicación entre procesos/hilos (Queue) | `task_queue`, `result_queue` |
| RF-09 Exclusión mutua (Lock) | `bitacora_lock`, `contador_lock` |
| RF-10 Parada temprana (Event) | `stop_event` (ver `tests/test_motores.py::TestParadaTemprana`) |
| RF-11 Medición de tiempos de alta precisión | `time.perf_counter()` / `time.time()` |
| RF-12 Métricas (Speedup/Eficiencia/Throughput) | `metrics.py` |
| RF-13 Reporte de vulnerabilidades | `report_generator.py` |
| RNF-01 Solo bibliotecas estándar | todo el proyecto (incl. `charts.py`: SVG a mano) |
| RNF-02 Integridad de datos concurrente | `construir_mapa_objetivos` + dedup en colectores (ver tests) |
| RNF-05 Diseño orientado a objetos | `auditors.py`: `BaseAuditor` (ABC) + 3 subclases |

## 6. Plan de pruebas sugerido para el informe

1. `python -m unittest discover -s tests -v` — evidencia de pruebas automatizadas.
2. Ejecutar `benchmark` con un dataset pequeño (n=10-15) sin `--extendido`
   para mostrar un caso rápido en vivo durante la presentación.
3. Ejecutar `benchmark` con `--extendido --workers 1 2 4 8` como corrida
   oficial de métricas — capturar la tabla, el análisis GIL vs. procesos
   impreso en consola, y las gráficas SVG generadas en `results/graficas/`.
4. Repetir el paso 3 con otro algoritmo (`--algoritmo md5` o `--algoritmo
   sha512`) para mostrar el soporte multi-algoritmo (RF-07).
5. Incluir en el documento técnico: la tabla comparativa, las gráficas SVG,
   el análisis de Speedup/Eficiencia/GIL (`docs/ARQUITECTURA.md` §6-8) y el
   reporte de vulnerabilidad generado (`results/reporte_vulnerabilidad.md`).
