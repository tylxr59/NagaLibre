//! Traced media/scroll actions, admitted only by wired paired transactions.
use super::Button;
use serde::Deserialize;
use std::sync::OnceLock;

#[derive(Deserialize)]
struct NativeAction {
    category: u8,
    data: Vec<u8>,
}

pub(super) fn supported(button: &Button) -> bool {
    static ACTIONS: OnceLock<Vec<NativeAction>> = OnceLock::new();
    ACTIONS
        .get_or_init(|| {
            serde_json::from_str(include_str!("../../devices/native-actions.json"))
                .expect("Invalid built-in native actions")
        })
        .iter()
        .any(|action| action.category == button.category && action.data == button.data)
}
