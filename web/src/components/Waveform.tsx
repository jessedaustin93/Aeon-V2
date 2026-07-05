import { useEffect, useRef } from "react";

// The signal signature: a scope trace on the console header. Quiet baseline
// when idle; a live amber waveform when Aeon is "transmitting" (streaming).
export function Waveform({ active, height = 34 }: { active: boolean; height?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    let t = 0;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const draw = () => {
      const w = canvas.clientWidth;
      const h = height;
      ctx.clearRect(0, 0, w, h);
      const mid = h / 2;
      const live = activeRef.current;
      const amp = live ? h * 0.32 : h * 0.06;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 2) {
        const p = x / w;
        // layered sines give an irregular, instrument-like trace
        const y =
          mid +
          Math.sin(p * 22 + t) * amp * (live ? 1 : 0.6) +
          Math.sin(p * 7 - t * 1.7) * amp * 0.4 * (live ? 1 : 0.3);
        x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.strokeStyle = live ? "#e8a44c" : "#26313c";
      ctx.lineWidth = live ? 1.6 : 1;
      ctx.shadowColor = live ? "rgba(232,164,76,0.5)" : "transparent";
      ctx.shadowBlur = live ? 8 : 0;
      ctx.stroke();

      if (!reduce) t += live ? 0.16 : 0.02;
      raf = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [height]);

  return <canvas ref={ref} style={{ width: "100%", height, display: "block" }} />;
}
