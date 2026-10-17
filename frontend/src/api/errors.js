export class AdapterError extends Error {
  constructor(message, { status = 500, code = "UNKNOWN_ERROR" } = {}) {
    super(message);
    this.name = "AdapterError";
    this.status = status;
    this.code = code;
  }
}
