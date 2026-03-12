export const motionEase = [0.4, 0, 0.2, 1] as const;

export const motionDurations = {
  fast: 0.12,
  normal: 0.2,
  slow: 0.3,
} as const;

export const motionTransitions = {
  springSoft: {
    type: "spring",
    damping: 24,
    stiffness: 280,
  },
  standard: {
    duration: motionDurations.normal,
    ease: motionEase,
  },
} as const;

export const motionVariants = {
  cardEnter: {
    initial: { opacity: 0, y: 10 },
    animate: { opacity: 1, y: 0 },
    transition: motionTransitions.standard,
  },
  dropdownEnter: {
    initial: { opacity: 0, scale: 0.96, y: 4 },
    animate: { opacity: 1, scale: 1, y: 0 },
    transition: motionTransitions.standard,
  },
  hoverLift: {
    whileHover: { scale: 1.02 },
    whileTap: { scale: 0.97 },
    transition: motionTransitions.springSoft,
  },
} as const;
