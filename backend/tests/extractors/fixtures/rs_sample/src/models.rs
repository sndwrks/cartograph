pub trait Greet {
    fn greet(&self);
}

pub struct Base;

impl Base {
    pub fn save(&self) -> bool {
        true
    }
}

pub struct Node {
    pub name: String,
}

impl Node {
    pub fn new() -> Self {
        Self { name: String::new() }
    }

    pub fn validate(&self) -> bool {
        true
    }
}

impl Greet for Node {
    fn greet(&self) {
        self.validate();
    }
}

pub fn render() -> &'static str {
    "models"
}
