//! Explicit model capabilities. A recognized USB ID does not establish vendor protocol support.
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::OnceLock;

#[derive(Debug, Deserialize, Serialize)]
pub struct BindingDefault {
    pub category: u8,
    pub data: Vec<u8>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct ControlDefault {
    pub id: String,
    pub name: String,
    pub button: u8,
    pub wire_id: u8,
    pub binding: BindingDefault,
    pub default_label: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct PlateDefaults {
    pub keys: Vec<String>,
    pub bindings: Vec<BindingDefault>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct Defaults {
    pub plates: BTreeMap<String, PlateDefaults>,
    pub controls: Vec<ControlDefault>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct Model {
    pub id: String,
    pub name: String,
    pub products: Vec<u16>,
    pub plates: Vec<String>,
    pub onboard: bool,
    pub faceplate: bool,
    pub verified: bool,
    pub defaults: Defaults,
}

pub fn naga_defaults() -> &'static Defaults {
    &lookup(0x1532, 0xa7)
        .expect("Missing wired Naga model")
        .defaults
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
            assert_eq!(model.defaults.plates.len(), model.plates.len());
            for plate in &model.plates {
                let defaults = &model.defaults.plates[plate];
                let count: usize = plate.parse().unwrap();
                assert_eq!(defaults.keys.len(), count);
                assert!(defaults.bindings.is_empty() || defaults.bindings.len() == count);
                if !model.onboard {
                    assert!(defaults.bindings.is_empty());
                }
            }
            let mut controls = BTreeSet::new();
            let mut addresses = BTreeSet::new();
            for control in &model.defaults.controls {
                assert!((13..=16).contains(&control.button) && controls.insert(control.button));
                assert!(
                    [0x34, 0x35, 0x6d, 0x60].contains(&control.wire_id)
                        && addresses.insert(control.wire_id)
                );
                assert!(!control.name.is_empty() && !control.default_label.is_empty());
                assert!(control.binding.data.len() <= 5);
            }
            for product in &model.products {
                assert!(products.insert(product));
                assert_eq!(lookup(0x1532, *product).unwrap().id, model.id);
            }
            if model.id != "naga_v2_pro" {
                assert!(!model.onboard && !model.faceplate && !model.verified);
                assert!(model.defaults.controls.is_empty());
            }
        }
        assert_eq!(
            naga_defaults()
                .controls
                .iter()
                .map(|c| (c.button, c.wire_id))
                .collect::<Vec<_>>(),
            vec![(13, 0x34), (14, 0x35), (15, 0x6d), (16, 0x60)]
        );
        assert!(lookup(0x1532, 0xffff).is_none());
        assert!(lookup(0x1234, 0xa7).is_none());
        for bluetooth in [0xa9, 0x92, 0xb5] {
            assert!(lookup(0x1532, bluetooth).is_none());
        }
    }
}
