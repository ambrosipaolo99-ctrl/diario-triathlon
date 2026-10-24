"""
Cifratura di stato e dati (AES-256-GCM, autenticata: un file alterato non si apre).

Stato   chiave casuale di 32 byte (segreto STATE_KEY), usata solo dentro GitHub Actions.
        Formato: b"DTS1" | nonce(12) | ciphertext+tag, con l'intestazione come dato autenticato.
Dati    chiave derivata dalla frase segreta (PBKDF2-SHA256, 600.000 iterazioni, sale casuale di 16 byte
        conservato nello stato); il telefono la ricava dalla frase e decifra in locale (WebCrypto).
        Formato: b"DTD1" | sale(16) | iterazioni(4, big endian) | nonce(12) | ciphertext+tag.
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

STATE_MAGIC = b"DTS1"
DATA_MAGIC = b"DTD1"
PBKDF2_ITERATIONS = 600_000         # raccomandazione OWASP 2023 per PBKDF2-HMAC-SHA256
MIN_PASSPHRASE = 20


class CryptoError(RuntimeError):
    pass


def state_key(b64: str | None) -> bytes:
    try:
        key = base64.b64decode(b64 or "", validate=True)
    except ValueError:
        key = b""
    if len(key) != 32:
        raise CryptoError("STATE_KEY mancante o non valida (servono 32 byte in base64)")
    return key


def seal_state(raw: bytes, key: bytes) -> bytes:
    nonce = os.urandom(12)
    return STATE_MAGIC + nonce + AESGCM(key).encrypt(nonce, raw, STATE_MAGIC)


def open_state(blob: bytes, key: bytes) -> bytes:
    if blob[:4] != STATE_MAGIC:
        raise CryptoError("stato in formato sconosciuto")
    try:
        return AESGCM(key).decrypt(blob[4:16], blob[16:], STATE_MAGIC)
    except Exception as exc:  # InvalidTag: chiave sbagliata o file alterato
        raise CryptoError("stato non decifrabile: chiave errata o file alterato") from exc


def data_key(passphrase: str | None, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    if not passphrase or len(passphrase) < MIN_PASSPHRASE:
        raise CryptoError(f"DATA_PASSPHRASE mancante o piu' corta di {MIN_PASSPHRASE} caratteri")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def seal_data(raw: bytes, key: bytes, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    nonce = os.urandom(12)
    header = DATA_MAGIC + salt + iterations.to_bytes(4, "big") + nonce
    return header + AESGCM(key).encrypt(nonce, raw, header)


def open_data(blob: bytes, key: bytes) -> bytes:
    """Solo per i test: il telefono fa la stessa cosa con WebCrypto."""
    header = blob[:36]
    if header[:4] != DATA_MAGIC:
        raise CryptoError("dati in formato sconosciuto")
    return AESGCM(key).decrypt(header[24:36], blob[36:], header)
