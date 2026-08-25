'use strict';
// Real (native-ARM) Android 7+: the game's System.load("libNianticLabsPlugin.so")
// throws "Expecting an absolute path of the library" (the API-24+ rule). On a real
// device there is no ARM translation layer, so we just need to turn the relative
// name into an absolute path under the app's nativeLibraryDir; the native ARM
// linker then loads the ARM .so directly.
//
// Frida 17: Java is under the bridge's .default export; bundle with frida-compile.
const Java = require('frida-java-bridge').default;

function libDir() {
  try {
    var ActivityThread = Java.use('android.app.ActivityThread');
    var app = ActivityThread.currentApplication();
    if (app !== null) {
      var d = app.getApplicationInfo().nativeLibraryDir.value;
      if (d && d.length > 0) return d;
    }
  } catch (e) {}
  return null;
}

function fix(name) {
  if (name && name.indexOf('/') === -1 && name.indexOf('.so') !== -1) {
    var dir = libDir();
    if (dir) {
      var abs = dir + '/' + name;
      console.log('[hook] "' + name + '" -> "' + abs + '"');
      return abs;
    }
    console.log('[hook] could not resolve nativeLibraryDir for ' + name);
  }
  return name;
}

Java.perform(function () {
  try {
    var System = Java.use('java.lang.System');
    System.load.overload('java.lang.String').implementation = function (name) {
      return this.load(fix(name));
    };
    console.log('[hook] System.load (absolute-path) hook installed');
  } catch (e) {
    console.log('[hook] System.load err: ' + e);
  }
  try {
    var Runtime = Java.use('java.lang.Runtime');
    Runtime.load0.overload('java.lang.Class', 'java.lang.String').implementation =
      function (cls, name) { return this.load0(cls, fix(name)); };
    console.log('[hook] Runtime.load0 (absolute-path) hook installed');
  } catch (e) {
    console.log('[hook] Runtime.load0 err: ' + e);
  }
});
