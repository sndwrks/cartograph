use crate::models::Node;
use std::collections::HashMap;

pub struct OrderService {
    repo: Node,
}

impl OrderService {
    pub fn new() -> Self {
        Self { repo: Node::new() }
    }

    pub fn check(&self) -> bool {
        true
    }

    pub fn save(&self, item: i32) -> i32 {
        let n = Node::new();
        n.validate();
        self.check();
        crate::util::render();
        self.repo.validate();
        let _m: HashMap<i32, i32> = HashMap::new();
        item
    }
}
