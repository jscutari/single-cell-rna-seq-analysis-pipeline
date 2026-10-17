import { useLayoutEffect, useRef, useState } from "react";
import "./SpiralBinding.css";

const FIRST_LOOP = 16;
const LOOP_SPACING = 55;

/** Spiral loops down the seam; the count follows the notebook's height. */
export function SpiralBinding() {
  const ref = useRef<HTMLDivElement>(null);
  const [count, setCount] = useState(19);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setCount(Math.ceil((el.clientHeight - FIRST_LOOP) / LOOP_SPACING) + 1);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="binding" aria-hidden="true" ref={ref}>
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className="binding-loop" style={{ top: FIRST_LOOP + i * LOOP_SPACING }} />
      ))}
    </div>
  );
}
