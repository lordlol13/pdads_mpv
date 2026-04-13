import { motion, AnimatePresence } from "motion/react";

interface SlotTextProps {
  text: string;
  className?: string;
}

export function SlotText({ text, className }: SlotTextProps) {
  const characters = text.split("");

  return (
    <span className={`inline-flex overflow-hidden ${className}`}>
      <AnimatePresence mode="wait">
        <motion.span
          key={text}
          className="inline-flex"
          initial="initial"
          animate="animate"
          exit="exit"
        >
          {characters.map((char, index) => (
            <motion.span
              key={index}
              variants={{
                initial: { y: "-100%", opacity: 0 },
                animate: { 
                  y: 0, 
                  opacity: 1,
                  transition: { 
                    delay: index * 0.01 + 0.1, // Even faster transition
                    duration: 0.3,
                    ease: [0.45, 0.05, 0.55, 0.95]
                  } 
                },
                exit: { 
                  y: "100%", 
                  opacity: 0,
                  transition: { 
                    delay: index * 0.005,
                    duration: 0.2,
                    ease: [0.45, 0.05, 0.55, 0.95]
                  } 
                }
              }}
              className="inline-block"
            >
              {char === " " ? "\u00A0" : char}
            </motion.span>
          ))}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}
