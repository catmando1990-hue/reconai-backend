"""
AES-256 encryption utilities for data at rest.

Provides symmetric encryption for sensitive data using AES-256-GCM.
"""

import os
import base64
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from cryptography.hazmat.backends import default_backend


class EncryptionService:
    """
    AES-256-GCM encryption service for sensitive data.

    Uses AES-256 in Galois/Counter Mode (GCM) which provides both
    confidentiality and authenticity.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize encryption service.

        Args:
            encryption_key: Base64-encoded 32-byte key. If not provided,
                          uses ENCRYPTION_KEY from environment.
        """
        if encryption_key is None:
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if not encryption_key:
                raise ValueError(
                    "ENCRYPTION_KEY environment variable must be set. "
                    "Generate with: python -c 'import os, base64; "
                    "print(base64.b64encode(os.urandom(32)).decode())'"
                )

        try:
            # Decode the base64 key
            self.key = base64.b64decode(encryption_key)
            if len(self.key) != 32:
                raise ValueError("Encryption key must be 32 bytes (256 bits)")
        except Exception as e:
            raise ValueError(f"Invalid encryption key format: {e}")

        self.aesgcm = AESGCM(self.key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string using AES-256-GCM.

        Args:
            plaintext: String to encrypt

        Returns:
            Base64-encoded string containing nonce + ciphertext + tag
        """
        if not plaintext:
            return ""

        # Generate a random 96-bit nonce (12 bytes)
        nonce = os.urandom(12)

        # Encrypt the plaintext
        ciphertext = self.aesgcm.encrypt(
            nonce,
            plaintext.encode('utf-8'),
            None  # No associated data
        )

        # Combine nonce + ciphertext and encode as base64
        encrypted_data = nonce + ciphertext
        return base64.b64encode(encrypted_data).decode('utf-8')

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a string encrypted with AES-256-GCM.

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If decryption fails (wrong key or corrupted data)
        """
        if not ciphertext:
            return ""

        try:
            # Decode base64
            encrypted_data = base64.b64decode(ciphertext)

            # Extract nonce (first 12 bytes) and ciphertext
            nonce = encrypted_data[:12]
            encrypted_message = encrypted_data[12:]

            # Decrypt
            plaintext = self.aesgcm.decrypt(nonce, encrypted_message, None)
            return plaintext.decode('utf-8')
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")

    def encrypt_file(self, file_path: str, output_path: Optional[str] = None) -> str:
        """
        Encrypt a file using AES-256-GCM.

        Args:
            file_path: Path to file to encrypt
            output_path: Path for encrypted file. If None, uses file_path + '.enc'

        Returns:
            Path to encrypted file
        """
        if output_path is None:
            output_path = file_path + '.enc'

        # Read the file
        with open(file_path, 'rb') as f:
            plaintext = f.read()

        # Generate nonce
        nonce = os.urandom(12)

        # Encrypt
        ciphertext = self.aesgcm.encrypt(nonce, plaintext, None)

        # Write nonce + ciphertext
        with open(output_path, 'wb') as f:
            f.write(nonce + ciphertext)

        return output_path

    def decrypt_file(self, encrypted_path: str, output_path: Optional[str] = None) -> str:
        """
        Decrypt a file encrypted with AES-256-GCM.

        Args:
            encrypted_path: Path to encrypted file
            output_path: Path for decrypted file. If None, removes '.enc' extension

        Returns:
            Path to decrypted file
        """
        if output_path is None:
            if encrypted_path.endswith('.enc'):
                output_path = encrypted_path[:-4]
            else:
                output_path = encrypted_path + '.dec'

        # Read encrypted file
        with open(encrypted_path, 'rb') as f:
            encrypted_data = f.read()

        # Extract nonce and ciphertext
        nonce = encrypted_data[:12]
        ciphertext = encrypted_data[12:]

        # Decrypt
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)

        # Write decrypted file
        with open(output_path, 'wb') as f:
            f.write(plaintext)

        return output_path


# Singleton instance
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """Get or create the global encryption service instance."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service


def encrypt_string(plaintext: str) -> str:
    """Convenience function to encrypt a string."""
    return get_encryption_service().encrypt(plaintext)


def decrypt_string(ciphertext: str) -> str:
    """Convenience function to decrypt a string."""
    return get_encryption_service().decrypt(ciphertext)


def generate_encryption_key() -> str:
    """
    Generate a new 256-bit encryption key.

    Returns:
        Base64-encoded 32-byte key suitable for ENCRYPTION_KEY env var
    """
    key = os.urandom(32)
    return base64.b64encode(key).decode('utf-8')


if __name__ == "__main__":
    # Generate a new key when run directly
    print("Generated AES-256 encryption key:")
    print(generate_encryption_key())
    print("\nAdd this to your .env file as:")
    print("ENCRYPTION_KEY=<key above>")
