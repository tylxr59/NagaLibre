//! Explicit model capabilities. A recognized USB ID does not authorize vendor writes.
use serde::{Deserialize, Serialize};
use std::sync::OnceLock;

#[derive(Debug, Deserialize, Serialize)]
pub struct Model {
    pub id: String,
    pub name: String,
    pub products: Vec<u16>,
    pub plates: Vec<String>,
    pub onboard: bool,
    pub faceplate: bool,
    pub verified: bool,
}

pub fn models() -> &'static [Model] {
    static MODELS: OnceLock<Vec<Model>> = OnceLock::new();
    MODELS.get_or_init(|| {
        serde_json::from_str(include_str!("../devices/models.json"))
            .expect("Invalid built-in device registry")
    })
}

pub fn lookup(vendor: u16, product: u16) -> Option<&'static Model> {
    (vendor == 0x1532)
        .then(|| {
            models()
                .iter()
                .find(|model| model.products.contains(&product))
        })
        .flatten()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn registry_keeps_unverified_devices_out_of_vendor_operations() {
        let mut ids = BTreeSet::new();
        let mut products = BTreeSet::new();
        for model in models() {
            assert!(ids.insert(&model.id));
            assert!(!model.plates.is_empty());
            for product in &model.products {
                assert!(products.insert(product));
                assert_eq!(lookup(0x1532, *product).unwrap().id, model.id);
            }
            if model.id != "naga_v2_pro" {
                assert!(!model.onboard && !model.faceplate && !model.verified);
            }
        }
        assert!(lookup(0x1532, 0xffff).is_none());
        assert!(lookup(0x1234, 0xa7).is_none());
        for bluetooth in [0xa9, 0x92, 0xb5] {
            assert!(lookup(0x1532, bluetooth).is_none());
        }
    }
}
