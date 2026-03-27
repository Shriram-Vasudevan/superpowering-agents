"use client";

import { useRef } from "react";
import Image from "next/image";
import {
  motion,
  useInView,
  useScroll,
  useTransform,
} from "framer-motion";
import useEmblaCarousel from "embla-carousel-react";
import Button from "@/components/Button";


/* ─── Images ─── */
const IMAGES = {
  FARM_1: "https://images.unsplash.com/photo-1633439299420-b37fb80eefb8?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxncmVlbiUyMGZhcm0lMjBmaWVsZCUyMHJvd3MlMjBjcm9wcyUyMHN1bnJpc2UlMjBhZXJpYWwlMjBhZ3JpY3VsdHVyYWx8ZW58MXwwfHx8MTc3NDU3NTgzNXww&ixlib=rb-4.1.0&q=80&w=1080",
  FARM_3: "https://images.unsplash.com/photo-1505990642933-77e40c9a2254?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwzfHxncmVlbiUyMGZhcm0lMjBmaWVsZCUyMHJvd3MlMjBjcm9wcyUyMHN1bnJpc2UlMjBhZXJpYWwlMjBhZ3JpY3VsdHVyYWx8ZW58MXwwfHx8MTc3NDU3NTgzNXww&ixlib=rb-4.1.0&q=85",
  FARM_4: "https://images.unsplash.com/photo-1683322850925-63997b771646?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw2fHxncmVlbiUyMGZhcm0lMjBmaWVsZCUyMHJvd3MlMjBjcm9wcyUyMHN1bnJpc2UlMjBhZXJpYWwlMjBhZ3JpY3VsdHVyYWx8ZW58MXwwfHx8MTc3NDU3NTgzNXww&ixlib=rb-4.1.0&q=85",
  FARM_5: "https://images.unsplash.com/photo-1751818430520-d2954873e314?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw1fHxncmVlbiUyMGZhcm0lMjBmaWVsZCUyMHJvd3MlMjBjcm9wcyUyMHN1bnJpc2UlMjBhZXJpYWwlMjBhZ3JpY3VsdHVyYWx8ZW58MXwwfHx8MTc3NDU3NTgzNXww&ixlib=rb-4.1.0&q=85",
  FOOD_1: "https://images.unsplash.com/photo-1690299564210-ff855826b278?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_4: "https://images.unsplash.com/photo-1544510807-1c0229035e63?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw0fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_5: "https://images.unsplash.com/photo-1771573042846-9f3631a48058?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw1fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_6: "https://images.unsplash.com/photo-1658041133672-17552737d6d3?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw2fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  INGREDIENT_1: "https://images.unsplash.com/photo-1645220559451-aaacbbd7bcc5?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxmcmVzaCUyMHNwcmluZyUyMHZlZ2V0YWJsZXMlMjBhc3BhcmFndXMlMjBwZWFzJTIwaGVyYnMlMjB3b29kZW4lMjBydXN0aWMlMjBjbG9zZSUyMHVwfGVufDF8MHx8fDE3NzQ1NzU4Mzh8MA&ixlib=rb-4.1.0&q=80&w=1080",
  CHEF_6: "https://images.unsplash.com/photo-1719329467670-5a4cb167bbf9?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw2fHxjaGVmJTIwY29va2luZyUyMGtpdGNoZW4lMjBwcm9mZXNzaW9uYWwlMjBkYXJrJTIwbW9vZHklMjBjdWxpbmFyeXxlbnwxfDB8fHwxNzc0NTc1ODM0fDA&ixlib=rb-4.1.0&q=85",
};

/* ─── Animation Variants ─── */
const fadeUpStagger = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08 } },
};

const fadeUpChild = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: "easeOut" as const },
  },
};

const blurScaleIn = {
  hidden: { opacity: 0, scale: 0.96, filter: "blur(8px)" },
  visible: {
    opacity: 1,
    scale: 1,
    filter: "blur(0px)",
    transition: { duration: 0.7, ease: "easeOut" as const },
  },
};

const textRevealClip = {
  hidden: { y: "100%" },
  visible: {
    y: "0%",
    transition: { duration: 0.8, ease: [0.16, 1, 0.3, 1] as const },
  },
};

function Section({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-100px" });
  return (
    <motion.section
      ref={ref}
      initial="hidden"
      animate={inView ? "visible" : "hidden"}
      variants={fadeUpStagger}
      className={className}
    >
      {children}
    </motion.section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 1 — HERO
   ═══════════════════════════════════════════════════════ */
function FarmHero() {
  return (
    <Section className="relative min-h-[85vh] flex items-center overflow-hidden">
      {/* Full-bleed farm landscape background */}
      <div className="absolute inset-0 overflow-hidden">
        <Image
          src={IMAGES.FARM_4}
          alt="Farm at sunset"
          fill
          className="object-cover"
          sizes="100vw"
          priority
          style={{ filter: "saturate(0.8) brightness(0.5)" }}
        />
        <div className="absolute inset-0 bg-charcoal/50" />
        <div className="absolute inset-0 grain-overlay" />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6 w-full py-24">
        <div className="flex flex-col md:flex-row items-center gap-16">
          <div className="md:w-[55%]">
            <div className="overflow-hidden mb-4">
              <motion.h1
                variants={textRevealClip}
                className="text-6xl sm:text-7xl lg:text-9xl text-cream font-light"
                style={{
                  fontFamily: "var(--font-display)",
                  WebkitTextStroke: "1px oklch(0.96 0.02 80 / 0.6)",
                  color: "transparent",
                }}
              >
                THE FARM
              </motion.h1>
            </div>
            <motion.p
              variants={fadeUpChild}
              className="text-cream/60 text-xl"
              style={{ fontFamily: "var(--font-body)" }}
            >
              12 Acres in Hillsboro, Oregon
            </motion.p>
          </div>

          <motion.div
            variants={blurScaleIn}
            className="md:w-[40%] relative h-[450px] md:h-[550px] -mb-16 grain-overlay"
          >
            <Image
              src={IMAGES.FARM_1}
              alt="Our farm"
              fill
              className="object-cover warm-tone"
              sizes="(max-width: 768px) 100vw, 40vw"
              priority
            />
          </motion.div>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 2 — SOURCING PHILOSOPHY
   ═══════════════════════════════════════════════════════ */
function SourcingSection() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const y = useTransform(scrollYProgress, [0, 1], [-30, 30]);

  return (
    <Section className="relative bg-[#1a1a1a] py-32 overflow-hidden noise-overlay">
      <div className="relative z-10 max-w-7xl mx-auto px-6">
        <div className="flex flex-col md:flex-row gap-16 items-start">
          {/* Left text */}
          <div className="md:w-[35%]">
            <div className="overflow-hidden mb-6">
              <motion.h2
                variants={textRevealClip}
                className="text-3xl sm:text-4xl text-cream font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Soil to Service
              </motion.h2>
            </div>
            <motion.p
              variants={fadeUpChild}
              className="text-cream/60 text-lg leading-relaxed mb-6"
              style={{ fontFamily: "var(--font-body)" }}
            >
              Our 12-acre farm in Hillsboro practices regenerative agriculture. No synthetic pesticides, no shortcuts. We rotate crops seasonally, build soil health with cover crops, and let the land rest when it needs to.
            </motion.p>
            <motion.p
              variants={fadeUpChild}
              className="text-cream/60 text-lg leading-relaxed mb-8"
              style={{ fontFamily: "var(--font-body)" }}
            >
              What grows determines the menu. What the land gives, we serve. It is the simplest philosophy and the hardest to execute.
            </motion.p>
            <motion.div variants={fadeUpChild}>
              <Button variant="ghost" size="md" arrow>
                Our Practices
              </Button>
            </motion.div>
          </div>

          {/* Right photo */}
          <motion.div
            variants={blurScaleIn}
            ref={ref}
            className="md:w-[65%] relative h-[500px] md:h-[650px] -mb-20 overflow-hidden"
          >
            <motion.div style={{ y }} className="absolute inset-[-30px] grain-overlay vignette">
              <Image
                src={IMAGES.FARM_4}
                alt="Farm aerial view"
                fill
                className="object-cover warm-tone"
                sizes="(max-width: 768px) 100vw, 65vw"
              />
            </motion.div>
          </motion.div>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 3 — WHAT WE GROW (Embla carousel)
   ═══════════════════════════════════════════════════════ */
function WhatWeGrowSection() {
  const [emblaRef] = useEmblaCarousel({ loop: true, align: "start" });

  const seasons = [
    {
      name: "Spring",
      items: "Asparagus, Peas, Radishes, Fiddlehead Ferns, Nettles, Spring Onions",
      image: IMAGES.INGREDIENT_1,
    },
    {
      name: "Summer",
      items: "Tomatoes, Corn, Berries, Squash Blossoms, Peppers, Stone Fruit",
      image: IMAGES.FOOD_1,
    },
    {
      name: "Fall",
      items: "Squash, Mushrooms, Apples, Pears, Root Vegetables, Hearty Greens",
      image: IMAGES.FOOD_5,
    },
    {
      name: "Winter",
      items: "Root Vegetables, Kale, Brussels Sprouts, Stored Grains, Preserves",
      image: IMAGES.FOOD_6,
    },
  ];

  return (
    <Section className="relative bg-cream py-32 overflow-hidden noise-overlay">
      <div className="relative z-10 max-w-7xl mx-auto px-6 mb-12">
        <motion.h2
          variants={fadeUpChild}
          className="text-4xl sm:text-5xl text-charcoal font-light"
          style={{ fontFamily: "var(--font-display)" }}
        >
          What We Grow
        </motion.h2>
      </div>

      <div className="relative z-10 px-6">
        <motion.div variants={blurScaleIn} className="overflow-hidden" ref={emblaRef}>
          <div className="flex gap-6">
            {seasons.map((season) => (
              <div
                key={season.name}
                className="flex-[0_0_66%] md:flex-[0_0_40%] min-w-[280px] bg-warm-white shadow-lg"
              >
                <div className="relative h-[300px] grain-overlay">
                  <Image
                    src={season.image}
                    alt={season.name}
                    fill
                    className="object-cover warm-tone"
                    sizes="(max-width: 768px) 66vw, 40vw"
                  />
                </div>
                <div className="p-8">
                  <h3
                    className="text-4xl sm:text-5xl lg:text-6xl text-charcoal mb-4 font-light"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {season.name}
                  </h3>
                  <p
                    className="text-charcoal/60 text-sm leading-relaxed"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    {season.items}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 4 — FARM-TO-TABLE NARRATIVE (3 editorial beats)
   ═══════════════════════════════════════════════════════ */
function NarrativeSection() {
  const beats = [
    {
      num: "01",
      title: "Harvest",
      desc: "Every morning at dawn, our farmers walk the rows. What they pick today becomes tonight's menu.",
      image: IMAGES.FARM_3,
      align: "left" as const,
    },
    {
      num: "02",
      title: "Kitchen",
      desc: "Chef Margaux and her team transform each harvest into dishes that honor the ingredient.",
      image: IMAGES.CHEF_6,
      align: "right" as const,
    },
    {
      num: "03",
      title: "Table",
      desc: "The final step: a plate that tells the story of the land, the season, and the hands that grew it.",
      image: IMAGES.FOOD_4,
      align: "center" as const,
    },
  ];

  return (
    <>
      {beats.map((beat) => (
        <NarrativeBeat key={beat.num} beat={beat} />
      ))}
    </>
  );
}

function NarrativeBeat({
  beat,
}: {
  beat: {
    num: string;
    title: string;
    desc: string;
    image: string;
    align: "left" | "right" | "center";
  };
}) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-100px" });
  const scrollRef = useRef(null);
  const { scrollYProgress } = useScroll({
    target: scrollRef,
    offset: ["start end", "end start"],
  });
  const y = useTransform(scrollYProgress, [0, 1], [-40, 40]);

  return (
    <motion.section
      ref={ref}
      initial="hidden"
      animate={inView ? "visible" : "hidden"}
      variants={fadeUpStagger}
      className="relative min-h-[70vh] flex items-center overflow-hidden"
    >
      <div ref={scrollRef} className="absolute inset-0 overflow-hidden">
        <motion.div style={{ y }} className="absolute inset-[-40px]">
          <Image
            src={beat.image}
            alt={beat.title}
            fill
            className={`object-cover ${beat.num === "03" ? "sepia-filter" : "warm-tone"}`}
            sizes="100vw"
          />
        </motion.div>
        <div className="absolute inset-0 bg-charcoal/50 mix-blend-multiply" />
        <div className="absolute inset-0 bg-amber/8 mix-blend-soft-light" />
        <div className="absolute inset-0 grain-overlay" />
        {beat.num === "03" && <div className="absolute inset-0 vignette" />}
      </div>

      {/* Oversized watermark */}
      <div
        className={`absolute top-8 ${beat.align === "right" ? "left-8" : "right-8"} text-[14rem] leading-none font-bold pointer-events-none select-none`}
        style={{
          fontFamily: "var(--font-display)",
          WebkitTextStroke: "1px oklch(0.96 0.02 80 / 0.08)",
          color: "transparent",
        }}
        aria-hidden
      >
        {beat.num}
      </div>

      <div className={`relative z-10 max-w-7xl mx-auto px-6 py-32 w-full ${beat.align === "center" ? "text-center" : ""}`}>
        <div className={`max-w-lg ${beat.align === "right" ? "ml-auto text-right" : beat.align === "center" ? "mx-auto" : ""}`}>
          <motion.h2
            variants={fadeUpChild}
            className="text-4xl sm:text-5xl lg:text-6xl text-cream font-light mb-6"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {beat.title}
          </motion.h2>
          <motion.p
            variants={fadeUpChild}
            className="text-cream/70 text-lg leading-relaxed"
            style={{ fontFamily: "var(--font-body)" }}
          >
            {beat.desc}
          </motion.p>
        </div>
      </div>
    </motion.section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 5 — VISIT CTA
   ═══════════════════════════════════════════════════════ */
function VisitCTA() {
  return (
    <Section className="relative min-h-[70vh] flex items-center overflow-hidden">
      <div className="absolute inset-0">
        <Image
          src={IMAGES.FARM_5}
          alt="Farm fields aerial"
          fill
          className="object-cover warm-tone"
          sizes="100vw"
        />
        <div className="absolute inset-0 bg-charcoal/30" />
        <div className="absolute inset-0 grain-overlay" />
        <div className="absolute inset-0 vignette" />
      </div>

      {/* Oversized watermark */}
      <div
        className="absolute top-16 right-8 text-[14rem] leading-none font-bold pointer-events-none select-none"
        style={{
          fontFamily: "var(--font-display)",
          WebkitTextStroke: "1px oklch(0.96 0.02 80 / 0.06)",
          color: "transparent",
        }}
        aria-hidden
      >
        VISIT
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6 py-24 w-full">
        <div className="flex flex-col md:flex-row items-center gap-16">
          <div className="md:w-[55%]">
            <div className="overflow-hidden mb-6">
              <motion.h2
                variants={textRevealClip}
                className="text-5xl sm:text-6xl lg:text-7xl text-cream font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Visit Our Farm
              </motion.h2>
            </div>
          </div>

          <motion.div
            variants={blurScaleIn}
            className="md:w-[40%] bg-charcoal/90 border border-amber/20 p-10"
          >
            <h3
              className="text-2xl text-cream mb-6 font-light"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Seasonal Open Days
            </h3>
            <ul
              className="space-y-3 text-cream/60 text-sm"
              style={{ fontFamily: "var(--font-body)" }}
            >
              <li>Saturdays, May through October</li>
              <li>10:00am &ndash; 2:00pm</li>
              <li>Farm tours, tastings, and seasonal workshops</li>
            </ul>
            <div className="mt-8">
              <Button variant="solid" size="lg" shimmer>
                Schedule a Visit
              </Button>
            </div>
          </motion.div>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   PAGE
   ═══════════════════════════════════════════════════════ */
export default function FarmPage() {
  return (
    <>
      <FarmHero />
      <SourcingSection />
      <WhatWeGrowSection />
      <NarrativeSection />
      <VisitCTA />
    </>
  );
}
