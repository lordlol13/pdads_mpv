import { useEffect, useRef } from "react";

interface Star {
  x: number;
  y: number;
  z: number;
}

export function InteractiveSpaceBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pointer = useRef<{ x: number | null; y: number | null }>({ x: null, y: null });
  const velocity = useRef({ x: 0, y: 0, tx: 0, ty: 0, z: 0.0005 });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId: number;
    let stars: Star[] = [];
    
    const STAR_COLOR = '#fff';
    const STAR_SIZE = 3;
    const STAR_MIN_SCALE = 0.2;
    const OVERFLOW_THRESHOLD = 50;
    
    let scale = window.devicePixelRatio || 1;
    let width = window.innerWidth * scale;
    let height = window.innerHeight * scale;

    const starCount = Math.floor((window.innerWidth + window.innerHeight) / 8);

    const placeStar = (star: Star) => {
      star.x = Math.random() * width;
      star.y = Math.random() * height;
    };

    const recycleStar = (star: Star) => {
      let direction = 'z';
      const vx = Math.abs(velocity.current.x);
      const vy = Math.abs(velocity.current.y);

      if (vx > 1 || vy > 1) {
        let axis;
        if (vx > vy) {
          axis = Math.random() < vx / (vx + vy) ? 'h' : 'v';
        } else {
          axis = Math.random() < vy / (vx + vy) ? 'v' : 'h';
        }

        if (axis === 'h') {
          direction = velocity.current.x > 0 ? 'l' : 'r';
        } else {
          direction = velocity.current.y > 0 ? 't' : 'b';
        }
      }

      star.z = STAR_MIN_SCALE + Math.random() * (1 - STAR_MIN_SCALE);

      if (direction === 'z') {
        star.z = 0.1;
        star.x = Math.random() * width;
        star.y = Math.random() * height;
      } else if (direction === 'l') {
        star.x = -OVERFLOW_THRESHOLD;
        star.y = height * Math.random();
      } else if (direction === 'r') {
        star.x = width + OVERFLOW_THRESHOLD;
        star.y = height * Math.random();
      } else if (direction === 't') {
        star.x = width * Math.random();
        star.y = -OVERFLOW_THRESHOLD;
      } else if (direction === 'b') {
        star.x = width * Math.random();
        star.y = height + OVERFLOW_THRESHOLD;
      }
    };

    const resize = () => {
      scale = window.devicePixelRatio || 1;
      width = window.innerWidth * scale;
      height = window.innerHeight * scale;
      canvas.width = width;
      canvas.height = height;
      stars.forEach(placeStar);
    };

    const initStars = () => {
      stars = [];
      for (let i = 0; i < starCount; i++) {
        stars.push({
          x: 0,
          y: 0,
          z: STAR_MIN_SCALE + Math.random() * (1 - STAR_MIN_SCALE)
        });
      }
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (pointer.current.x !== null && pointer.current.y !== null) {
        const ox = e.clientX - pointer.current.x;
        const oy = e.clientY - pointer.current.y;
        velocity.current.tx = velocity.current.tx + (ox / 8 * scale) * -1;
        velocity.current.ty = velocity.current.ty + (oy / 8 * scale) * -1;
      }
      pointer.current.x = e.clientX;
      pointer.current.y = e.clientY;
    };

    const handleMouseLeave = () => {
      pointer.current.x = null;
      pointer.current.y = null;
    };

    const animate = () => {
      ctx.clearRect(0, 0, width, height);

      // Update velocity
      velocity.current.tx *= 0.96;
      velocity.current.ty *= 0.96;
      velocity.current.x += (velocity.current.tx - velocity.current.x) * 0.8;
      velocity.current.y += (velocity.current.ty - velocity.current.y) * 0.8;

      stars.forEach((star) => {
        star.x += velocity.current.x * star.z;
        star.y += velocity.current.y * star.z;

        star.x += (star.x - width / 2) * velocity.current.z * star.z;
        star.y += (star.y - height / 2) * velocity.current.z * star.z;
        star.z += velocity.current.z;

        if (star.x < -OVERFLOW_THRESHOLD || star.x > width + OVERFLOW_THRESHOLD || star.y < -OVERFLOW_THRESHOLD || star.y > height + OVERFLOW_THRESHOLD) {
          recycleStar(star);
        }

        // Render
        ctx.beginPath();
        ctx.lineCap = 'round';
        ctx.lineWidth = STAR_SIZE * star.z * scale;
        ctx.globalAlpha = 0.5 + 0.5 * Math.random();
        ctx.strokeStyle = STAR_COLOR;

        ctx.moveTo(star.x, star.y);

        let tailX = velocity.current.x * 2;
        let tailY = velocity.current.y * 2;

        if (Math.abs(tailX) < 0.1) tailX = 0.5;
        if (Math.abs(tailY) < 0.1) tailY = 0.5;

        ctx.lineTo(star.x + tailX, star.y + tailY);
        ctx.stroke();
      });

      animationFrameId = requestAnimationFrame(animate);
    };

    window.addEventListener("resize", resize);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseleave", handleMouseLeave);
    
    initStars();
    resize();
    animate();

    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseleave", handleMouseLeave);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 w-full h-full z-[-1] pointer-events-none bg-black"
    />
  );
}

