pub fn helper(x: i32) -> i32 {
    x * 2
}

pub fn cached_helper(x: i32) -> i32 {
    helper(x)
}

pub fn render() -> &'static str {
    "util"
}

#[cfg(test)]
mod tests {
    use super::helper;

    #[test]
    fn test_helper() {
        helper(2);
        super::render();
    }
}
