var leftPad = require("left-pad");

function binLabel(row, slot) {
  return "R" + leftPad(row, 2, "0") + "-S" + leftPad(slot, 3, "0");
}

module.exports = { binLabel: binLabel };
