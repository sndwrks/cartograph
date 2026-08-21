const { helper, other: renamed } = require("./helpers.cjs");

function run() {
  renamed(2);
  return helper(1);
}

module.exports = run;
