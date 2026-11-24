# Reporte de Vulnerabilidad de Contraseñas

**Fecha de generacion:** 2026-11-23T17:23:20
**Algoritmo de hash auditado:** SHA256
**Nivel de riesgo global:** CRITICO

## 1. Resumen Ejecutivo

De un total de **20** credenciales objetivo, el sistema logro recuperar **16** (80.0%) mediante un ataque de diccionario hibrido (diccionario base + mutaciones de mayusculas/numeros/simbolos).

Las credenciales no recuperadas corresponden, en su mayoria, a contraseñas largas y aleatorias fuera del espacio de busqueda del diccionario, lo que confirma que la longitud y aleatoriedad reales siguen siendo la defensa mas efectiva frente a este tipo de ataque.

## 2. Credenciales Recuperadas

| # | Usuario | Contraseña recuperada | Hash (prefijo) | Encontrado por | Tiempo (s) |
|---|---------|------------------------|-----------------|-----------------|------------|
| 1 | usuario_006 | `BUSTER15` | `3103fcdc4764...` | worker-3 | 1.8927 |
| 2 | usuario_018 | `Mustang37$` | `a7f4d90a5e4f...` | worker-1 | 1.9026 |
| 3 | usuario_002 | `robert` | `4007d4629229...` | worker-8 | 2.2959 |
| 4 | usuario_003 | `Charlie1994#` | `d211aadf3837...` | worker-5 | 2.3223 |
| 5 | usuario_014 | `Eagle2005*` | `fb40e321ecf3...` | worker-6 | 2.9885 |
| 6 | usuario_005 | `power57$` | `1c32728a3a36...` | worker-7 | 4.3864 |
| 7 | usuario_020 | `triumph` | `9bb8c09c1ccb...` | worker-4 | 4.6795 |
| 8 | usuario_012 | `never67.` | `4276f405677c...` | worker-7 | 5.5505 |
| 9 | usuario_013 | `wall` | `4d8aaa64f685...` | worker-3 | 7.0458 |
| 10 | usuario_019 | `wellness` | `bc90a50b2fa0...` | worker-4 | 7.7677 |
| 11 | usuario_015 | `animal` | `ab91a82d14cf...` | worker-1 | 8.7674 |
| 12 | usuario_004 | `bronze` | `fcbbcd5a59bf...` | worker-6 | 9.2178 |
| 13 | usuario_017 | `crystal` | `60a0f78b507f...` | worker-7 | 9.3490 |
| 14 | usuario_007 | `Carbon87!` | `db6c274c4030...` | worker-8 | 9.6560 |
| 15 | usuario_009 | `iron` | `04e9c0db87e7...` | worker-6 | 9.7760 |
| 16 | usuario_010 | `radon76` | `4800bf755332...` | worker-7 | 10.0162 |

## 3. Tabla Comparativa de Rendimiento

```
Configuracion  | Tiempo(s) | Descifrados | Hashes eval. | Throughput(h/s) | Speedup | Eficiencia(%)
---------------+-----------+-------------+--------------+-----------------+---------+--------------
secuencial     | 19.6221   | 16/20       | 7,416,430    | 377,962.3       | 1.00x   | 100.0%       
hilos (N=1)    | 23.4058   | 16/20       | 7,416,430    | 316,862.8       | 0.84x   | 83.8%        
hilos (N=2)    | 20.9647   | 16/20       | 7,416,430    | 353,758.0       | 0.94x   | 46.8%        
hilos (N=4)    | 17.7477   | 16/20       | 7,416,430    | 417,880.5       | 1.11x   | 27.6%        
hilos (N=8)    | 29.0631   | 16/20       | 7,416,430    | 255,183.5       | 0.68x   | 8.4%         
procesos (N=1) | 18.0461   | 16/20       | 7,416,430    | 410,970.2       | 1.09x   | 108.7%       
procesos (N=2) | 14.4764   | 16/20       | 7,416,430    | 512,310.4       | 1.36x   | 67.8%        
procesos (N=4) | 10.7775   | 16/20       | 7,416,430    | 688,137.4       | 1.82x   | 45.5%        
procesos (N=8) | 10.6284   | 16/20       | 7,416,430    | 697,792.3       | 1.85x   | 23.1%        
```

```
Speedup relativo (T_secuencial / T_paralelo):

secuencial       | ########################### 1.00x
hilos (N=1)      | ####################### 0.84x
hilos (N=2)      | ######################### 0.94x
hilos (N=4)      | ############################## 1.11x
hilos (N=8)      | ################## 0.68x
procesos (N=1)   | ############################# 1.09x
procesos (N=2)   | ##################################### 1.36x
procesos (N=4)   | ################################################# 1.82x
procesos (N=8)   | ################################################## 1.85x
```

```
Eficiencia paralela (Speedup / N_trabajadores):

secuencial       | ################################################## 100.0%
hilos (N=1)      | ########################################## 83.8%
hilos (N=2)      | ####################### 46.8%
hilos (N=4)      | ############## 27.6%
hilos (N=8)      | #### 8.4%
procesos (N=1)   | ################################################## 108.7%
procesos (N=2)   | ################################## 67.8%
procesos (N=4)   | ####################### 45.5%
procesos (N=8)   | ############ 23.1%
```

## 4. Recomendaciones de Seguridad

- Exigir contraseñas de 14+ caracteres generadas aleatoriamente (gestor de contraseñas) en lugar de palabras de diccionario con variaciones predecibles.
- Aplicar *salting* unico por usuario y funciones de hash lentas para credenciales (bcrypt, scrypt o Argon2) en lugar de MD5/SHA-256/SHA-512 sin sal.
- Forzar autenticacion multifactor (MFA) para reducir el impacto de una contraseña comprometida.
