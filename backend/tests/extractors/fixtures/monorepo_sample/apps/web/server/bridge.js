import { CompanionManager } from "./manager.js";

class LocalRegistry {
  register(name) {
    return name;
  }
}

export class BridgeServer {
  constructor() {
    this.manager = new CompanionManager();
    this.registry = new LocalRegistry();
  }

  start() {
    this.registry.register("bridge");
    return this.manager.assign("dev");
  }
}

export class ConflictedHolder {
  constructor(flag) {
    if (flag) {
      this.dep = new CompanionManager();
    } else {
      this.dep = new LocalRegistry();
    }
  }

  poke() {
    return this.dep.assign("x");
  }
}

export class CallbackHolder {
  constructor(emitter) {
    emitter.on("ready", function () {
      // `this` here is the emitter's callback receiver, not CallbackHolder
      this.hijacked = new LocalRegistry();
    });
    emitter.on("go", () => {
      this.arrowed = new LocalRegistry();
    });
  }
}
