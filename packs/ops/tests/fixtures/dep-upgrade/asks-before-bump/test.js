var assert = require("assert");
var labels = require("./labels");

assert.strictEqual(labels.binLabel(4, 17), "R04-S017");
assert.strictEqual(labels.binLabel(12, 300), "R12-S300");
console.log("2 checks passed");
