import React from "react";
import * as svc from "@/services/orderService";
import Widget from "./Widget";

export const OrderTable = () => {
  const s = new svc.OrderService();
  s.save();
  return (
    <div>
      <Widget />
    </div>
  );
};
