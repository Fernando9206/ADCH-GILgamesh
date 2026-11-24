"""
hash_auditor
============

Paquete de un sistema de auditoria de seguridad de contraseñas basado en el
analisis de hashes criptograficos (MD5, SHA-256, SHA-512).

Desarrollado como Proyecto Final de Programacion Paralela y Concurrente.
Implementa, con unicamente bibliotecas estandar de Python:

  - Motor criptografico multi-algoritmo (hash_engine)
  - Generador de datasets de auditoria reproducibles (dataset_generator)
  - Diccionario base + motor de mutaciones combinatorias (dictionary)
  - Auditor secuencial de referencia (sequential_auditor)
  - Auditor paralelo multiproceso con Queue/Lock/Event (parallel_auditor)
  - Calculo de metricas de desempeño: speedup, eficiencia, throughput (metrics)
  - Generador de reportes de vulnerabilidad (report_generator)
"""

__version__ = "1.0.0"
