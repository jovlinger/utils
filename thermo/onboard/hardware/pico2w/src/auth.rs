use core::fmt::Write;

use base64ct::{Base64, Encoding};
use ed25519_dalek::{Signer, SigningKey};
use heapless::String;
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ZoneAuthError {
    Base64Decode,
    UnsupportedKeyFormat,
    BufferTooSmall,
    SigningFailed,
}

pub struct ZoneAuth {
    signing_key: SigningKey,
}

impl ZoneAuth {
    pub fn from_base64_key(raw: &str) -> Result<Self, ZoneAuthError> {
        let mut decoded = [0_u8; 128];
        let key_bytes =
            Base64::decode(raw, &mut decoded).map_err(|_| ZoneAuthError::Base64Decode)?;
        let seed = ed25519_seed_from_key_bytes(key_bytes)?;
        Ok(Self {
            signing_key: SigningKey::from_bytes(seed),
        })
    }

    pub fn sign_headers<const SIG: usize, const TS: usize>(
        &self,
        method: &str,
        path: &str,
        body: &[u8],
        zone_name: &'static str,
        epoch_seconds: u64,
    ) -> Result<SignedHeaders<SIG, TS>, ZoneAuthError> {
        let mut body_hash: String<64> = String::new();
        write_sha256_hex(body, &mut body_hash)?;

        let mut payload: String<256> = String::new();
        write!(
            payload,
            "{}\n{}\n{}\n{}",
            method, path, epoch_seconds, body_hash
        )
        .map_err(|_| ZoneAuthError::BufferTooSmall)?;

        let signature = self
            .signing_key
            .try_sign(payload.as_bytes())
            .map_err(|_| ZoneAuthError::SigningFailed)?;
        let mut encoded_buf = [0_u8; 96];
        let encoded = Base64::encode(&signature.to_bytes(), &mut encoded_buf)
            .map_err(|_| ZoneAuthError::BufferTooSmall)?;

        let mut signature_b64: String<SIG> = String::new();
        signature_b64
            .push_str(encoded)
            .map_err(|_| ZoneAuthError::BufferTooSmall)?;
        let mut timestamp: String<TS> = String::new();
        write!(timestamp, "{}", epoch_seconds).map_err(|_| ZoneAuthError::BufferTooSmall)?;

        Ok(SignedHeaders {
            signature_b64,
            timestamp,
            zone_name,
        })
    }
}

pub struct SignedHeaders<const SIG: usize, const TS: usize> {
    pub signature_b64: String<SIG>,
    pub timestamp: String<TS>,
    pub zone_name: &'static str,
}

fn ed25519_seed_from_key_bytes(bytes: &[u8]) -> Result<&[u8; 32], ZoneAuthError> {
    if bytes.len() == 32 {
        return bytes
            .try_into()
            .map_err(|_| ZoneAuthError::UnsupportedKeyFormat);
    }

    let mut index: usize = 0;
    while index + 34 <= bytes.len() {
        if bytes[index] == 0x04 && bytes[index + 1] == 0x20 {
            return bytes[index + 2..index + 34]
                .try_into()
                .map_err(|_| ZoneAuthError::UnsupportedKeyFormat);
        }
        index += 1;
    }
    Err(ZoneAuthError::UnsupportedKeyFormat)
}

fn write_sha256_hex<const N: usize>(body: &[u8], out: &mut String<N>) -> Result<(), ZoneAuthError> {
    let digest = Sha256::digest(body);
    for byte in digest {
        write!(out, "{:02x}", byte).map_err(|_| ZoneAuthError::BufferTooSmall)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{ed25519_seed_from_key_bytes, write_sha256_hex, ZoneAuth};
    use base64ct::{Base64, Encoding};
    use heapless::String;

    #[test]
    fn extracts_raw_seed() {
        let seed = [7_u8; 32];

        assert_eq!(ed25519_seed_from_key_bytes(&seed), Ok(&seed));
    }

    #[test]
    fn extracts_pkcs8_der_seed() {
        let mut der = [0_u8; 48];
        der[0..16].copy_from_slice(&[
            0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x04, 0x22,
            0x04, 0x20,
        ]);
        der[16..].copy_from_slice(&[9_u8; 32]);

        assert_eq!(ed25519_seed_from_key_bytes(&der), Ok(&[9_u8; 32]));
    }

    #[test]
    fn signs_request_headers() {
        let mut seed_b64_buf = [0_u8; 48];
        let seed = [1_u8; 32];
        let seed_b64 = Base64::encode(&seed, &mut seed_b64_buf).unwrap();
        let auth = ZoneAuth::from_base64_key(seed_b64).unwrap();

        let headers = auth
            .sign_headers::<96, 16>("POST", "/zone/test/sensors", b"{}", "test", 1_700_000_000)
            .unwrap();

        assert_eq!(headers.signature_b64.len(), 88);
        assert_eq!(headers.timestamp.as_str(), "1700000000");
        assert_eq!(headers.zone_name, "test");
    }

    #[test]
    fn sha256_hex_matches_known_empty_object_hash() {
        let mut out: String<64> = String::new();

        write_sha256_hex(b"{}", &mut out).unwrap();

        assert_eq!(
            out.as_str(),
            "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        );
    }
}
