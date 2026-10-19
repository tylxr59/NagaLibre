//! Naga V2 Pro hardware-module getter recovered from the model-specific controller.
use crate::onboard::{Mouse, Transport};
use anyhow::{Result, ensure};
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Faceplate {
    pub module_id: u8,
    pub buttons: Option<u8>,
}

pub fn read<T: Transport>(mouse: &mut Mouse<T>) -> Result<Faceplate> {
    let bytes = mouse.transport.exchange(0, 0xb9, &[0], 0)?;
    ensure!(bytes.len() == 1, "Invalid hardware-module reply");
    let module_id = bytes[0];
    Ok(Faceplate {
        module_id,
        buttons: match module_id {
            1 => Some(2),
            3 => Some(12),
            4 => Some(6),
            _ => None,
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::onboard::Identity;

    struct Reply(Vec<u8>);
    impl Transport for Reply {
        fn identity(&self) -> Identity {
            unreachable!()
        }
        fn exchange(
            &mut self,
            class: u8,
            command: u8,
            payload: &[u8],
            echo: usize,
        ) -> Result<Vec<u8>> {
            assert_eq!((class, command, payload, echo), (0, 0xb9, &[0][..], 0));
            Ok(self.0.clone())
        }
    }

    #[test]
    fn module_ids_and_unrecognized_plates_remain_distinct() {
        for (id, expected) in [
            (1, Some(2)),
            (3, Some(12)),
            (4, Some(6)),
            (0, None),
            (2, None),
            (255, None),
        ] {
            let result = read(&mut Mouse {
                transport: Reply(vec![id]),
            })
            .unwrap();
            assert_eq!(result.module_id, id);
            assert_eq!(result.buttons, expected);
        }
        for bytes in [vec![], vec![3, 0]] {
            assert!(
                read(&mut Mouse {
                    transport: Reply(bytes)
                })
                .is_err()
            );
        }
    }
}
