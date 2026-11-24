"""Pruebas del motor criptografico multi-algoritmo (RF-07)."""

import hashlib
import unittest

from hash_auditor.hash_engine import (
    algoritmos_soportados,
    calcular_hash,
    detectar_algoritmo_por_longitud,
    normalizar_algoritmo,
    obtener_constructor,
    tamano_hash_hex,
)


class TestHashEngine(unittest.TestCase):
    def test_algoritmos_soportados(self):
        self.assertEqual(algoritmos_soportados(), ["md5", "sha256", "sha512"])

    def test_calcular_hash_coincide_con_hashlib(self):
        password = "Hunter2!"
        self.assertEqual(calcular_hash(password, "md5"), hashlib.md5(password.encode()).hexdigest())
        self.assertEqual(calcular_hash(password, "sha256"), hashlib.sha256(password.encode()).hexdigest())
        self.assertEqual(calcular_hash(password, "sha512"), hashlib.sha512(password.encode()).hexdigest())

    def test_normalizar_algoritmo_acepta_variantes(self):
        self.assertEqual(normalizar_algoritmo("SHA-256"), "sha256")
        self.assertEqual(normalizar_algoritmo("  MD5  "), "md5")
        self.assertEqual(normalizar_algoritmo("Sha_512"), "sha512")

    def test_normalizar_algoritmo_rechaza_invalido(self):
        with self.assertRaises(ValueError):
            normalizar_algoritmo("sha1")

    def test_obtener_constructor_funciona_igual_que_calcular_hash(self):
        hash_fn = obtener_constructor("sha256")
        self.assertEqual(hash_fn(b"abc").hexdigest(), calcular_hash("abc", "sha256"))

    def test_tamano_hash_hex(self):
        self.assertEqual(tamano_hash_hex("md5"), 32)
        self.assertEqual(tamano_hash_hex("sha256"), 64)
        self.assertEqual(tamano_hash_hex("sha512"), 128)

    def test_detectar_algoritmo_por_longitud(self):
        self.assertEqual(detectar_algoritmo_por_longitud(calcular_hash("x", "md5")), "md5")
        self.assertEqual(detectar_algoritmo_por_longitud(calcular_hash("x", "sha256")), "sha256")
        self.assertEqual(detectar_algoritmo_por_longitud(calcular_hash("x", "sha512")), "sha512")

    def test_detectar_algoritmo_longitud_invalida(self):
        with self.assertRaises(ValueError):
            detectar_algoritmo_por_longitud("abc123")  # muy corto, longitud no soportada

    def test_detectar_algoritmo_caracteres_no_hex(self):
        with self.assertRaises(ValueError):
            detectar_algoritmo_por_longitud("g" * 64)  # 'g' no es hexadecimal


if __name__ == "__main__":
    unittest.main()
