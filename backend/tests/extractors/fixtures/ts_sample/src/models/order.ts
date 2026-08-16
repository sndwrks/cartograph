export interface Orderable {
  id: number;
}

export class Order implements Orderable {
  id: number;

  total(): number {
    return this.id;
  }
}

export class SpecialOrder extends Order {}

export function render(): string {
  return "order";
}
