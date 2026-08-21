import OrderPage from "./orderPage";
import Renamed from "./orderPage";

export function show(): void {
  const page = new OrderPage();
  page.open();
  new Renamed();
}
