"""
Pruebas de los tres motores de auditoria (secuencial / hilos / procesos):

  - Equivalencia de resultados entre motores (deben encontrar exactamente
    las mismas credenciales, sin importar la arquitectura de ejecucion).
  - Parada temprana (RF-10): el `Event` compartido debe detener a todos
    los trabajadores en cuanto se recupera el 100% de las cuentas, sin
    agotar el espacio de busqueda completo.
  - Integridad concurrente (RNF-02): ningun hallazgo debe perderse,
    incluyendo el caso de dos usuarios con la MISMA contraseña (mismo hash).

Estas pruebas usan datasets pequeños y `incluir_extendido=False` para que
la suite se ejecute en segundos, no en minutos.
"""

import tempfile
import unittest
from pathlib import Path

from hash_auditor.auditors import AuditorHilos, AuditorProcesos, AuditorSecuencial
from hash_auditor.dataset_generator import RegistroObjetivo
from hash_auditor.dictionary import estimar_total_candidatos
from hash_auditor.hash_engine import calcular_hash

# Diccionario sintetico pequeño y 100% controlado para que las pruebas
# sean deterministas y rapidas (no depende de data/diccionario_base.txt).
PALABRAS_PRUEBA = [f"clave{i:02d}" for i in range(40)]
ALGORITMO = "sha256"

# Diccionario mas grande, usado SOLO en las pruebas de parada temprana
# (ver clase TestParadaTemprana). Con un espacio de busqueda tan pequeño
# como el de PALABRAS_PRUEBA (17,640 candidatos), 2 trabajadores -sean
# hilos O PROCESOS- pueden agotarlo por completo en pocos milisegundos,
# antes de que el proceso/hilo principal tenga su primer turno de CPU
# para leer `result_queue` y activar `stop_event`: en ese caso no hay
# nada "temprano" que detener, simplemente ya no queda trabajo (esto
# causo un test flaky tanto en hilos como, mas tarde, en procesos -- ver
# docs/ANALISIS_PROYECTO.md). Con 3000 palabras el espacio de busqueda es
# lo bastante grande como para dejar un margen real y confiable donde
# observar la parada temprana, sin que la prueba deje de correr en bien
# menos de un segundo en el caso normal.
PALABRAS_GRANDES = [f"clave{i:04d}" for i in range(3000)]

# Las bitacoras de estas pruebas son archivos de descarte: antes se
# escribian en `results/_test_bitacora_*.log` y quedaban como basura tras
# correr la suite (docs/ANALISIS_PROYECTO.md). Se usa un directorio
# temporal del sistema operativo, creado una vez para todo el modulo
# (en `setUpModule`, no al importar) y borrado automaticamente al
# terminar, sin tocar `results/`.
_DIR_TEMPORAL: tempfile.TemporaryDirectory | None = None


def setUpModule():  # noqa: N802 (nombre requerido por unittest)
    global _DIR_TEMPORAL
    _DIR_TEMPORAL = tempfile.TemporaryDirectory(prefix="hash_auditor_tests_")


def tearDownModule():  # noqa: N802 (nombre requerido por unittest)
    _DIR_TEMPORAL.cleanup()


def _bitacora_temporal(nombre: str) -> Path:
    return Path(_DIR_TEMPORAL.name) / f"{nombre}.log"


def _objetivo(usuario_id: str, password: str) -> RegistroObjetivo:
    return RegistroObjetivo(usuario_id, calcular_hash(password, ALGORITMO), ALGORITMO)


class TestEquivalenciaEntreMotores(unittest.TestCase):
    """Los tres motores deben recuperar exactamente las mismas credenciales."""

    @classmethod
    def setUpClass(cls):
        cls.objetivos = [
            _objetivo("usuario_1", "clave00"),
            _objetivo("usuario_2", "Clave01!"),
            _objetivo("usuario_3", "clave99_no_existe_en_el_diccionario"),  # no debe encontrarse
        ]

    def _set_hallazgos(self, resultado):
        return {(h.usuario_id, h.password) for h in resultado.hallazgos}

    def test_secuencial_vs_hilos(self):
        r_sec = AuditorSecuencial(PALABRAS_PRUEBA, ALGORITMO).ejecutar(self.objetivos)
        r_hilos = AuditorHilos(PALABRAS_PRUEBA, ALGORITMO, num_trabajadores=2,
                                bitacora_path=_bitacora_temporal("hilos")).ejecutar(self.objetivos)
        self.assertEqual(self._set_hallazgos(r_sec), self._set_hallazgos(r_hilos))
        self.assertEqual(r_sec.descifrados, 2)  # el tercer objetivo no es descifrable

    def test_secuencial_vs_procesos(self):
        r_sec = AuditorSecuencial(PALABRAS_PRUEBA, ALGORITMO).ejecutar(self.objetivos)
        r_proc = AuditorProcesos(PALABRAS_PRUEBA, ALGORITMO, num_trabajadores=2,
                                  bitacora_path=_bitacora_temporal("procesos")).ejecutar(self.objetivos)
        self.assertEqual(self._set_hallazgos(r_sec), self._set_hallazgos(r_proc))
        self.assertEqual(r_proc.descifrados, 2)


class TestParadaTemprana(unittest.TestCase):
    """RF-10: el sistema debe detenerse apenas se recupera el 100%, sin agotar el espacio."""

    def test_procesos_se_detiene_antes_de_agotar_el_espacio(self):
        # Se usa PALABRAS_GRANDES (3000 palabras), no PALABRAS_PRUEBA (40):
        # con un espacio de busqueda tan chico como el de 40 palabras
        # (17,640 candidatos), 2 procesos pueden agotarlo por completo en
        # unos pocos milisegundos -- antes de que el proceso principal
        # tenga su primer turno de CPU para leer `result_queue` y activar
        # `stop_event` -- sin que haya nada "temprano" que detener. Esto
        # causo un fallo intermitente real en una corrida en vivo de la
        # suite (docs/ANALISIS_PROYECTO.md, Revision 3). Con 3000 palabras
        # el margen es real y confiable, y la prueba sigue corriendo en
        # bien menos de un segundo en el caso normal.
        objetivos = [_objetivo("u1", "clave0000"), _objetivo("u2", "clave0001")]
        resultado = AuditorProcesos(
            PALABRAS_GRANDES, ALGORITMO, num_trabajadores=2, tam_lote_palabras=1,
            bitacora_path=_bitacora_temporal("parada"),
        ).ejecutar(objetivos)

        self.assertEqual(resultado.descifrados, 2)
        total_espacio = estimar_total_candidatos(len(PALABRAS_GRANDES), incluir_extendido=False)
        self.assertLess(
            resultado.candidatos_evaluados, total_espacio * 0.5,
            "El Event de parada temprana no interrumpio a los trabajadores a tiempo "
            "(se evaluo mas de la mitad del espacio de busqueda)."
        )

    def test_hilos_se_detiene_antes_de_agotar_el_espacio(self):
        # NOTA sobre PALABRAS_GRANDES: con `threading`, el GIL cambia de
        # contexto entre hilos cada ~5ms (sys.getswitchinterval()), no por
        # candidato, por lo que el margen necesario para observar la
        # parada temprana de forma confiable es aun mayor que con
        # procesos (ver docstring de PALABRAS_GRANDES arriba).
        objetivos = [_objetivo("u1", "clave0000"), _objetivo("u2", "clave0001")]
        resultado = AuditorHilos(
            PALABRAS_GRANDES, ALGORITMO, num_trabajadores=2, tam_lote_palabras=1,
            bitacora_path=_bitacora_temporal("parada_hilos"),
        ).ejecutar(objetivos)

        self.assertEqual(resultado.descifrados, 2)
        total_espacio = estimar_total_candidatos(len(PALABRAS_GRANDES), incluir_extendido=False)
        self.assertLess(
            resultado.candidatos_evaluados, total_espacio * 0.5,
            "El Event de parada temprana no interrumpio a los hilos a tiempo "
            "(se evaluo mas de la mitad del espacio de busqueda)."
        )


class TestIntegridadConcurrente(unittest.TestCase):
    """RNF-02: ningun hallazgo debe perderse, ni siquiera con contraseñas duplicadas."""

    def test_dos_usuarios_con_la_misma_contrasena(self):
        objetivos = [
            _objetivo("usuario_a", "clave05"),
            _objetivo("usuario_b", "clave05"),  # mismo password -> mismo hash
            _objetivo("usuario_c", "clave10"),
        ]
        resultado = AuditorProcesos(
            PALABRAS_PRUEBA, ALGORITMO, num_trabajadores=2,
            bitacora_path=_bitacora_temporal("duplicados"),
        ).ejecutar(objetivos)

        usuarios_encontrados = {h.usuario_id for h in resultado.hallazgos}
        self.assertEqual(resultado.total_objetivos, 3, "total_objetivos debe contar CUENTAS, no hashes unicos")
        self.assertEqual(usuarios_encontrados, {"usuario_a", "usuario_b", "usuario_c"})
        self.assertEqual(resultado.descifrados, 3)

    def test_repeticiones_no_pierden_hallazgos(self):
        """Corre la misma auditoria varias veces: nunca debe perderse un hallazgo por una condicion de carrera."""
        objetivos = [_objetivo("u1", "clave00"), _objetivo("u2", "clave01"), _objetivo("u3", "clave02")]
        for intento in range(3):
            resultado = AuditorProcesos(
                PALABRAS_PRUEBA, ALGORITMO, num_trabajadores=4,
                bitacora_path=_bitacora_temporal(f"repeticion_{intento}"),
            ).ejecutar(objetivos)
            self.assertEqual(resultado.descifrados, 3, f"Intento {intento}: se perdio un hallazgo")


if __name__ == "__main__":
    unittest.main()
