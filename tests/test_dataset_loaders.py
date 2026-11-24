"""
Pruebas de carga de hashes objetivo (RF-01/RF-07): CSV, TXT plano,
autodeteccion de algoritmo y validacion de consistencia.
"""

import tempfile
import unittest
from pathlib import Path

from hash_auditor.dataset_generator import (
    cargar_objetivos,
    cargar_objetivos_csv,
    cargar_objetivos_texto,
    guardar_objetivos_csv,
    validar_algoritmo_coincide,
)
from hash_auditor.hash_engine import calcular_hash
from hash_auditor.dataset_generator import RegistroObjetivo


class TestCargaTexto(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="hash_auditor_tests_")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_linea_con_usuario_y_sin_usuario(self):
        h1 = calcular_hash("dragon", "sha256")
        h2 = calcular_hash("robert", "sha256")
        ruta = self.dir / "hashes.txt"
        ruta.write_text(f"usuario_x:{h1}\n{h2}\n", encoding="utf-8")

        objetivos = cargar_objetivos_texto(ruta)
        self.assertEqual(len(objetivos), 2)
        self.assertEqual(objetivos[0].usuario_id, "usuario_x")
        self.assertEqual(objetivos[0].hash, h1)
        self.assertEqual(objetivos[0].algoritmo, "sha256")
        # a la segunda linea (sin usuario_id explicito) se le asigna uno automatico
        self.assertTrue(objetivos[1].usuario_id.startswith("usuario_"))

    def test_autodeteccion_de_algoritmo_por_longitud(self):
        h_md5 = calcular_hash("x", "md5")
        h_sha512 = calcular_hash("x", "sha512")
        ruta = self.dir / "mixto.txt"
        ruta.write_text(f"{h_md5}\n{h_sha512}\n", encoding="utf-8")

        objetivos = cargar_objetivos_texto(ruta)
        self.assertEqual(objetivos[0].algoritmo, "md5")
        self.assertEqual(objetivos[1].algoritmo, "sha512")

    def test_archivo_vacio_lanza_error(self):
        ruta = self.dir / "vacio.txt"
        ruta.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            cargar_objetivos_texto(ruta)

    def test_archivo_solo_con_comentarios_lanza_error(self):
        # Edge case detectado en docs/ANALISIS_PROYECTO.md: un archivo con
        # solo comentarios no esta "vacio" (tiene lineas), pero tampoco
        # contiene ningun hash valido -- debe fallar igual que un CSV vacio.
        ruta = self.dir / "solo_comentarios.txt"
        ruta.write_text("# nota 1\n# nota 2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            cargar_objetivos_texto(ruta)

    def test_archivo_inexistente(self):
        with self.assertRaises(FileNotFoundError):
            cargar_objetivos_texto(self.dir / "no_existe.txt")

    def test_dispatcher_elige_por_extension(self):
        h = calcular_hash("dragon", "sha256")
        ruta_txt = self.dir / "a.txt"
        ruta_txt.write_text(f"{h}\n", encoding="utf-8")
        objetivos_txt = cargar_objetivos(ruta_txt)
        self.assertEqual(len(objetivos_txt), 1)

        ruta_csv = self.dir / "b.csv"
        guardar_objetivos_csv([RegistroObjetivo("u1", h, "sha256")], ruta_csv)
        objetivos_csv = cargar_objetivos(ruta_csv)
        self.assertEqual(len(objetivos_csv), 1)
        self.assertEqual(objetivos_csv[0].usuario_id, "u1")


class TestValidacionAlgoritmo(unittest.TestCase):
    def test_coincide_no_lanza_error(self):
        h = calcular_hash("x", "sha256")
        objetivos = [RegistroObjetivo("u1", h, "sha256")]
        validar_algoritmo_coincide(objetivos, "sha256")  # no debe lanzar

    def test_no_coincide_lanza_error_claro(self):
        h = calcular_hash("x", "sha256")
        objetivos = [RegistroObjetivo("u1", h, "sha256")]
        with self.assertRaises(ValueError) as ctx:
            validar_algoritmo_coincide(objetivos, "md5")
        self.assertIn("sha256", str(ctx.exception))

    def test_csv_con_algoritmo_inconsistente_con_su_propio_hash_lanza_error(self):
        # Un CSV que DECLARA sha256 pero cuyo hash es en realidad de MD5
        # (32 caracteres) debe fallar al cargarse, no al auditar (RF-07).
        with tempfile.TemporaryDirectory(prefix="hash_auditor_tests_") as tmp:
            ruta = Path(tmp) / "corrupto.csv"
            h_md5 = calcular_hash("x", "md5")
            ruta.write_text(f"usuario_id,hash,algoritmo\nu1,{h_md5},sha256\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cargar_objetivos_csv(ruta)


if __name__ == "__main__":
    unittest.main()
