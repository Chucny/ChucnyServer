const bridge = require('frida-java-bridge');
console.log('typeof default =', typeof bridge);
console.log('has perform =', typeof bridge.perform);
console.log('has use =', typeof bridge.use);
console.log('keys =', Object.keys(bridge).slice(0, 25).join(','));
if (bridge.default) {
  console.log('has .default, typeof .default.perform =', typeof bridge.default.perform);
}
