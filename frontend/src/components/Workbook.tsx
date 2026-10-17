import type { ReactNode } from "react";
import "./Workbook.css";

export function Workbook({ children }: { children: ReactNode }) {
  return <div className="workbook">{children}</div>;
}
