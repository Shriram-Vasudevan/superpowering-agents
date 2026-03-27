"use client";

import { useRef } from "react";
import Image from "next/image";
import {
  motion,
  useInView,
  useScroll,
  useTransform,
} from "framer-motion";
import CountUp from "react-countup";
import {
  IconArrowRight,
} from "@tabler/icons-react";
import useEmblaCarousel from "embla-carousel-react";
import Button from "@/components/Button";

/* ─── Images ─── */
const IMAGES = {
  FARM_1: "https://images.unsplash.com/photo-1633439299420-b37fb80eefb8?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxncmVlbiUyMGZhcm0lMjBmaWVsZCUyMHJvd3MlMjBjcm9wcyUyMHN1bnJpc2UlMjBhZXJpYWwlMjBhZ3JpY3VsdHVyYWx8ZW58MXwwfHx8MTc3NDU3NTgzNXww&ixlib=rb-4.1.0&q=85",
  FARM_2: "https://images.unsplash.com/photo-1624194936938-42d3eb7beafa?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwyfHxncmVlbiUyMGZhcm0lMjBmaWVsZCUyMHJvd3MlMjBjcm9wcyUyMHN1bnJpc2UlMjBhZXJpYWwlMjBhZ3JpY3VsdHVyYWx8ZW58MXwwfHx8MTc3NDU3NTgzNXww&ixlib=rb-4.1.0&q=85",
  FARM_3: "https://images.unsplash.com/photo-1505990642933-77e40c9a2254?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwzfHxncmVlbiUyMGZhcm0lMjBmaWVsZCUyMHJvd3MlMjBjcm9wcyUyMHN1bnJpc2UlMjBhZXJpYWwlMjBhZ3JpY3VsdHVyYWx8ZW58MXwwfHx8MTc3NDU3NTgzNXww&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_1: "https://images.unsplash.com/photo-1690299564210-ff855826b278?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_3: "https://images.unsplash.com/photo-1660505465468-c898ea7ff674?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwzfHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_4: "https://images.unsplash.com/photo-1544510807-1c0229035e63?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw0fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_5: "https://images.unsplash.com/photo-1771573042846-9f3631a48058?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw1fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_6: "https://images.unsplash.com/photo-1658041133672-17552737d6d3?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw2fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_7: "https://images.unsplash.com/photo-1692197275441-40c874f40385?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw3fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_8: "https://images.unsplash.com/photo-1626200419884-427c1108bc27?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw5fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_9: "https://images.unsplash.com/photo-1676037150408-4b59a542fa7c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw4fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_10: "https://images.unsplash.com/photo-1587207850226-ba5ac4c96c9c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxMHx8Z291cm1ldCUyMHBsYXRlZCUyMGRpc2glMjBmaW5lJTIwZGluaW5nJTIwc2Vhc29uYWwlMjB2ZWdldGFibGVzJTIwZWxlZ2FudCUyMHByZXNlbnRhdGlvbnxlbnwxfDB8fHwxNzc0NTc1ODI5fDA&ixlib=rb-4.1.0&q=80&w=1080",
  CHEF_4: "https://images.unsplash.com/photo-1660486275943-8ed936d9536b?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw0fHxjaGVmJTIwY29va2luZyUyMGtpdGNoZW4lMjBwcm9mZXNzaW9uYWwlMjBkYXJrJTIwbW9vZHklMjBjdWxpbmFyeXxlbnwxfDB8fHwxNzc0NTc1ODM0fDA&ixlib=rb-4.1.0&q=85",
  INGREDIENT_1: "https://images.unsplash.com/photo-1645220559451-aaacbbd7bcc5?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxmcmVzaCUyMHNwcmluZyUyMHZlZ2V0YWJsZXMlMjBhc3BhcmFndXMlMjBwZWFzJTIwaGVyYnMlMjB3b29kZW4lMjBydXN0aWMlMjBjbG9zZSUyMHVwfGVufDF8MHx8fDE3NzQ1NzU4Mzh8MA&ixlib=rb-4.1.0&q=80&w=1080",
  INTERIOR_1: "https://images.unsplash.com/photo-1761116183308-6a23c287a605?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxmYXJtJTIwdG8lMjB0YWJsZSUyMHJlc3RhdXJhbnQlMjBpbnRlcmlvciUyMGNhbmRsZWxpdCUyMHdhcm0lMjBtb29keSUyMGV2ZW5pbmclMjBkaW5pbmd8ZW58MXwwfHx8MTc3NDU3NTgyOHww&ixlib=rb-4.1.0&q=80&w=1080",
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

/* ─── Section Wrapper with InView ─── */
function Section({
  children,
  className = "",
  id,
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-100px" });
  return (
    <motion.section
      ref={ref}
      id={id}
      initial="hidden"
      animate={inView ? "visible" : "hidden"}
      variants={fadeUpStagger}
      className={className}
    >
      {children}
    </motion.section>
  );
}

/* ─── Parallax Image ─── */
function ParallaxImage({
  src,
  alt,
  className = "",
  containerClassName = "",
  speed = 0.4,
}: {
  src: string;
  alt: string;
  className?: string;
  containerClassName?: string;
  speed?: number;
}) {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const y = useTransform(scrollYProgress, [0, 1], [-30 * speed, 30 * speed]);

  return (
    <div ref={ref} className={`relative overflow-hidden ${containerClassName}`}>
      <motion.div style={{ y }} className="h-full w-full">
        <Image
          src={src}
          alt={alt}
          fill
          className={`object-cover ${className}`}
          sizes="(max-width: 768px) 100vw, 50vw"
        />
      </motion.div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 1 — HERO
   ═══════════════════════════════════════════════════════ */
function HeroSection() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const imgY = useTransform(scrollYProgress, [0, 1], [0, 120]);

  return (
    <section ref={ref} className="relative min-h-screen flex items-center overflow-hidden">
      {/* Full-bleed background image with parallax */}
      <div className="absolute inset-0 overflow-hidden">
        <motion.div style={{ y: imgY }} className="absolute inset-[-80px]">
          <Image
            src={IMAGES.INTERIOR_1}
            alt="Maison Verte dining room"
            fill
            className="object-cover warm-tone"
            sizes="100vw"
            priority
          />
        </motion.div>
        {/* Dark gradient overlay — heavier at bottom for text legibility */}
        <div className="absolute inset-0" style={{ background: "linear-gradient(to bottom, oklch(0.10 0.01 60 / 0.3) 0%, oklch(0.10 0.01 60 / 0.7) 60%, oklch(0.10 0.01 60 / 0.88) 100%)" }} />
        <div className="absolute inset-0 grain-overlay" />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6 w-full py-24">
        <motion.div variants={fadeUpChild} className="mb-6">
          <span
            className="text-amber text-sm tracking-[0.3em] uppercase"
            style={{ fontFamily: "var(--font-body)" }}
          >
            Portland, Oregon &mdash; Est. 2018
          </span>
        </motion.div>

        <div className="overflow-hidden mb-8">
          <motion.h1
            variants={textRevealClip}
            className="text-5xl sm:text-7xl lg:text-[6.5rem] text-cream leading-[0.92] font-light"
            style={{ fontFamily: "var(--font-display)" }}
          >
            From Our Farm
            <br />
            to Your Table
          </motion.h1>
        </div>

        <motion.p
          variants={fadeUpChild}
          className="text-cream/60 text-lg max-w-md mb-10"
          style={{ fontFamily: "var(--font-body)" }}
        >
          Seasonal Pacific Northwest cuisine rooted in our 12-acre Hillsboro farm.
        </motion.p>

        <motion.div variants={fadeUpChild} className="flex flex-wrap gap-4">
          <Button variant="solid" size="lg" shimmer href="/reserve">
            Reserve a Table
          </Button>
          <Button variant="ghost" size="lg" arrow href="/menu">
            View Menu
          </Button>
        </motion.div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 2 — PHILOSOPHY
   ═══════════════════════════════════════════════════════ */
function PhilosophySection() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const bgY = useTransform(scrollYProgress, [0, 1], [-40, 40]);

  return (
    <Section className="relative min-h-[80vh] flex items-center overflow-hidden bg-[#0f0f0f]">
      {/* Full-bleed FARM_2 background with parallax */}
      <div ref={ref} className="absolute inset-0 overflow-hidden">
        <motion.div style={{ y: bgY }} className="absolute inset-[-60px]">
          <Image
            src={IMAGES.FARM_2}
            alt="Farm rows at dawn"
            fill
            className="object-cover warm-tone"
            sizes="100vw"
          />
        </motion.div>
        <div className="absolute inset-0 bg-[#0f0f0f]/70" />
        <div className="absolute inset-0 grain-overlay" />
      </div>

      {/* Oversized outlined TERROIR watermark */}
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-[10rem] sm:text-[16rem] lg:text-[22rem] leading-none font-bold pointer-events-none select-none whitespace-nowrap"
        style={{
          fontFamily: "var(--font-display)",
          WebkitTextStroke: "1px oklch(0.96 0.02 80 / 0.05)",
          color: "transparent",
        }}
        aria-hidden
      >
        TERROIR
      </div>

      <div className="relative z-10 max-w-4xl mx-auto px-6 py-32">
        <motion.blockquote
          variants={fadeUpChild}
          className="text-3xl sm:text-4xl lg:text-5xl text-cream italic leading-[1.2] font-light mb-8"
          style={{ fontFamily: "var(--font-display)" }}
        >
          &ldquo;We don&apos;t just serve food. We tend the soil it grows from.&rdquo;
        </motion.blockquote>

        <motion.div variants={fadeUpChild} className="w-16 h-[1px] bg-amber mb-8" />

        <motion.p
          variants={fadeUpChild}
          className="text-cream/60 text-base sm:text-lg leading-relaxed max-w-xl mb-10"
          style={{ fontFamily: "var(--font-body)" }}
        >
          Every plate at Maison Verte begins in the rich volcanic soil of our Hillsboro farm.
          We practice seasonal rotation, hand-harvesting, and zero-spray cultivation — because
          flavor starts with the land, not the kitchen.
        </motion.p>

        <motion.div variants={fadeUpChild}>
          <Button variant="ghost" size="md" arrow href="/farm">
            Visit the Farm
          </Button>
        </motion.div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 3 — SEASONAL MENU PREVIEW
   ═══════════════════════════════════════════════════════ */
function MenuPreviewSection() {
  const dishes = [
    {
      name: "Nettle Risotto with Morel Mushrooms",
      description: "Arborio rice, foraged Pacific Northwest morels, aged parmesan, chive oil",
      price: "$28",
    },
    {
      name: "Pan-Seared Copper River Salmon",
      description: "Spring vegetables, nettle beurre blanc, preserved lemon, microgreens",
      price: "$38",
    },
    {
      name: "Roasted Spring Lamb with Fiddlehead Ferns",
      description: "Slow-braised shoulder, root vegetable puree, rosemary jus, baby carrots",
      price: "$42",
    },
  ];

  return (
    <Section className="relative bg-[#0a0a0a] py-32 overflow-hidden noise-overlay">
      <div className="relative z-10 max-w-7xl mx-auto px-6">
        <div className="flex flex-col lg:flex-row gap-16">
          {/* Left: Menu listing */}
          <div className="lg:w-[55%]">
            <motion.div variants={fadeUpChild} className="mb-16">
              <span
                className="text-amber text-sm tracking-[0.3em] uppercase block mb-4"
                style={{ fontFamily: "var(--font-body)" }}
              >
                Spring 2026
              </span>
              <h2
                className="text-4xl sm:text-5xl lg:text-6xl text-cream font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                What&apos;s Growing Now
              </h2>
            </motion.div>

            <div>
              {dishes.map((dish, i) => (
                <motion.div
                  key={dish.name}
                  variants={fadeUpChild}
                  className={`py-8 ${i < dishes.length - 1 ? "border-b border-amber/20" : ""}`}
                >
                  <div className="flex items-baseline justify-between mb-2">
                    <h3
                      className="text-xl sm:text-2xl text-cream font-light"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {dish.name}
                    </h3>
                    <span
                      className="text-amber text-xl ml-6 shrink-0"
                      style={{ fontFamily: "var(--font-display)" }}
                    >
                      {dish.price}
                    </span>
                  </div>
                  <p
                    className="text-cream/40 text-sm italic"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    {dish.description}
                  </p>
                </motion.div>
              ))}
            </div>

            <motion.div variants={fadeUpChild} className="mt-12">
              <Button variant="ghost" size="lg" arrow href="/menu">
                View Full Menu
              </Button>
            </motion.div>
          </div>

          {/* Right: Hero dish image */}
          <motion.div
            variants={blurScaleIn}
            className="lg:w-[45%] relative h-[500px] lg:h-auto lg:-mr-6 lg:-my-16 grain-overlay"
          >
            <Image
              src={IMAGES.FOOD_1}
              alt="Seasonal plated dish"
              fill
              className="object-cover warm-tone"
              sizes="(max-width: 1024px) 100vw, 45vw"
            />
          </motion.div>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 4 — CHEF
   ═══════════════════════════════════════════════════════ */
function ChefSection() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const bgY = useTransform(scrollYProgress, [0, 1], [-40, 40]);

  return (
    <Section className="relative min-h-[80vh] flex items-center overflow-hidden">
      {/* Background image with parallax */}
      <div ref={ref} className="absolute inset-0 overflow-hidden">
        <motion.div style={{ y: bgY }} className="absolute inset-[-60px]">
          <Image
            src={IMAGES.CHEF_4}
            alt="Chef at work"
            fill
            className="object-cover warm-tone"
            sizes="100vw"
          />
        </motion.div>
        <div className="absolute inset-0 bg-[#0a0a0a]/60" />
        <div className="absolute inset-0 grain-overlay" />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6 py-32 w-full">
        <div className="max-w-lg">
          <motion.div variants={fadeUpChild}>
            <span
              className="text-amber text-sm tracking-[0.3em] uppercase block mb-4"
              style={{ fontFamily: "var(--font-body)" }}
            >
              Meet Our Chef
            </span>
          </motion.div>
          <motion.h2
            variants={fadeUpChild}
            className="text-4xl sm:text-5xl text-cream mb-6 font-light"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Chef Margaux Bellamy
          </motion.h2>
          <motion.p
            variants={fadeUpChild}
            className="text-cream/70 text-lg leading-relaxed"
            style={{ fontFamily: "var(--font-body)" }}
          >
            James Beard semifinalist, 2024. Margaux trained under Thomas Keller at The French Laundry before returning to Portland to champion hyper-local, soil-to-plate cuisine. Every dish tells the story of our farm.
          </motion.p>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 5 — FARM NUMBERS
   ═══════════════════════════════════════════════════════ */
function FarmNumbersSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-100px" });

  const stats = [
    { value: 12, suffix: "", label: "Acres" },
    { value: 2, suffix: "", label: "Locations" },
    { value: 150, suffix: "+", label: "Dishes" },
    { value: 8, suffix: "", label: "Years" },
  ];

  return (
    <section ref={ref} className="relative py-32 overflow-hidden">
      {/* Farm photo background */}
      <div className="absolute inset-0 overflow-hidden">
        <Image
          src={IMAGES.FARM_3}
          alt="Our Hillsboro farm"
          fill
          className="object-cover warm-tone"
          sizes="100vw"
        />
        <div className="absolute inset-0 bg-[#0a0a0a]/75" />
        <div className="absolute inset-0 grain-overlay" />
      </div>

      <motion.div
        initial="hidden"
        animate={inView ? "visible" : "hidden"}
        variants={fadeUpStagger}
        className="relative z-10 max-w-6xl mx-auto px-6"
      >
        <div className="flex flex-wrap justify-between gap-12 md:gap-0">
          {stats.map((stat) => (
            <motion.div
              key={stat.label}
              variants={fadeUpChild}
              className="text-center w-[calc(50%-24px)] md:w-auto md:flex-1"
            >
              <div
                className="text-6xl sm:text-7xl lg:text-8xl text-cream font-light leading-none"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {inView ? (
                  <CountUp end={stat.value} duration={2.5} suffix={stat.suffix} />
                ) : (
                  "0"
                )}
              </div>
              <span
                className="text-cream/50 text-xs sm:text-sm tracking-[0.2em] uppercase mt-3 block"
                style={{ fontFamily: "var(--font-body)" }}
              >
                {stat.label}
              </span>
            </motion.div>
          ))}
        </div>
      </motion.div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 6 — TESTIMONIAL
   ═══════════════════════════════════════════════════════ */
function TestimonialSection() {
  return (
    <Section className="relative bg-[#0a0a0a] py-40 overflow-hidden noise-overlay">
      <div className="relative z-10 max-w-5xl mx-auto px-6 text-center">
        <motion.div variants={fadeUpChild} className="w-full h-px bg-amber/20 mb-16" />

        <div className="overflow-hidden">
          <motion.blockquote
            variants={textRevealClip}
            className="text-3xl sm:text-4xl lg:text-5xl text-cream italic leading-[1.2] font-light"
            style={{ fontFamily: "var(--font-display)" }}
          >
            &ldquo;The most extraordinary dining experience in the Pacific Northwest.&rdquo;
          </motion.blockquote>
        </div>

        <motion.p
          variants={fadeUpChild}
          className="text-amber mt-8 text-lg"
          style={{ fontFamily: "var(--font-body)" }}
        >
          &mdash; Portland Monthly
        </motion.p>

        <motion.div variants={fadeUpChild} className="w-full h-px bg-amber/20 mt-16" />
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 7 — GALLERY (Embla)
   ═══════════════════════════════════════════════════════ */
function GallerySection() {
  const [emblaRef] = useEmblaCarousel({ loop: true, align: "start" });

  const photos = [
    IMAGES.FOOD_1,
    IMAGES.FOOD_5,
    IMAGES.FOOD_6,
    IMAGES.FOOD_7,
    IMAGES.FOOD_8,
    IMAGES.FOOD_9,
  ];

  return (
    <Section className="relative bg-[#0a0a0a] py-32 overflow-hidden">
      <div className="relative z-10 max-w-[100vw] px-6">
        <div className="overflow-hidden" ref={emblaRef}>
          <div className="flex gap-4">
            {photos.map((src, i) => (
              <div
                key={i}
                className="relative flex-[0_0_33.33%] min-w-[280px] h-[65vh] grain-overlay"
              >
                <Image
                  src={src}
                  alt={`Gallery image ${i + 1}`}
                  fill
                  className="object-cover warm-tone"
                  sizes="33vw"
                />
              </div>
            ))}
          </div>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 8 — INGREDIENT MARQUEE
   ═══════════════════════════════════════════════════════ */
function MarqueeSection() {
  const items =
    "Morel Mushrooms \u2022 Fiddlehead Ferns \u2022 Spring Peas \u2022 Rhubarb \u2022 Nettles \u2022 Wild Salmon \u2022 Dungeness Crab \u2022 ";
  const repeated = items.repeat(4);

  return (
    <section className="relative bg-[#0f0f0f] py-12 overflow-hidden noise-overlay">
      <div className="relative z-10">
        <div className="w-full h-px bg-amber/10 mb-6" />

        {/* Row 1 */}
        <div className="overflow-hidden whitespace-nowrap mb-4">
          <div className="animate-ticker inline-block">
            <span
              className="text-cream/40 text-2xl italic"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {repeated}
            </span>
          </div>
        </div>

        {/* Row 2 — reverse direction */}
        <div className="overflow-hidden whitespace-nowrap">
          <div className="animate-ticker-reverse inline-block">
            <span
              className="text-cream/40 text-2xl italic"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {repeated}
            </span>
          </div>
        </div>

        <div className="w-full h-px bg-amber/10 mt-6" />
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 9 — LOCATIONS
   ═══════════════════════════════════════════════════════ */
function LocationsSection() {
  const locations = [
    {
      name: "Pearl District",
      image: IMAGES.FOOD_3,
      address: "412 NW 13th Ave, Portland, OR 97209",
      hours: "Tue\u2013Sun, 5:00pm \u2013 10:00pm",
      phone: "(503) 555-0142",
    },
    {
      name: "Alberta Arts District",
      image: IMAGES.FOOD_10,
      address: "2817 NE Alberta St, Portland, OR 97211",
      hours: "Wed\u2013Sun, 5:30pm \u2013 10:30pm",
      phone: "(503) 555-0198",
    },
  ];

  return (
    <Section className="relative bg-[#0f0f0f] py-32 overflow-hidden noise-overlay">
      <div className="relative z-10 max-w-6xl mx-auto px-6">
        <div className="flex flex-col md:flex-row gap-12 md:gap-0">
          {locations.map((loc, i) => (
            <motion.div
              key={loc.name}
              variants={blurScaleIn}
              className={`flex-1 ${i === 0 ? "md:pr-12 md:border-r md:border-amber/20" : "md:pl-12"}`}
            >
              <div className="relative h-[300px] grain-overlay mb-8">
                <Image
                  src={loc.image}
                  alt={loc.name}
                  fill
                  className="object-cover warm-tone"
                  sizes="(max-width: 768px) 100vw, 50vw"
                />
              </div>
              <h3
                className="text-2xl sm:text-3xl text-cream mb-6 font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {loc.name}
              </h3>
              <div
                className="space-y-2 text-cream/50 text-sm"
                style={{ fontFamily: "var(--font-body)" }}
              >
                <p>{loc.address}</p>
                <p>{loc.hours}</p>
                <p>{loc.phone}</p>
              </div>
              <div className="mt-6">
                <Button variant="underline" size="sm">
                  Get Directions
                </Button>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 10 — RESERVATION CTA
   ═══════════════════════════════════════════════════════ */
function ReservationCTASection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-100px" });

  return (
    <section
      ref={ref}
      className="relative min-h-screen flex items-center justify-center overflow-hidden"
    >
      {/* Full-bleed moody food photo background */}
      <div className="absolute inset-0 overflow-hidden">
        <Image
          src={IMAGES.FOOD_4}
          alt="Fine dining ambiance"
          fill
          className="object-cover"
          sizes="100vw"
          style={{ filter: "saturate(0.7) brightness(0.4)" }}
        />
        <div className="absolute inset-0 bg-charcoal/60 mix-blend-multiply" />
        <div className="absolute inset-0 grain-overlay" />
      </div>

      <motion.div
        initial="hidden"
        animate={inView ? "visible" : "hidden"}
        variants={fadeUpStagger}
        className="relative z-10 max-w-5xl mx-auto px-6 text-center"
      >
        <div className="overflow-hidden mb-6">
          <motion.h2
            variants={textRevealClip}
            className="text-5xl sm:text-7xl lg:text-8xl text-cream font-light tracking-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Your Table Awaits
          </motion.h2>
        </div>

        <motion.div
          variants={fadeUpChild}
          className="w-16 h-[1px] bg-amber/40 mx-auto mb-8"
        />

        <motion.p
          variants={fadeUpChild}
          className="text-cream/60 text-lg sm:text-xl max-w-xl mx-auto mb-14"
          style={{ fontFamily: "var(--font-body)" }}
        >
          Experience seasonal cuisine rooted in the land. Book your evening at Maison Verte.
        </motion.p>

        <motion.div
          variants={fadeUpChild}
          className="flex flex-wrap gap-5 justify-center"
        >
          <Button variant="solid" size="lg" shimmer href="/reserve" arrow>
            Reserve Now
          </Button>
          <Button variant="outline-white" size="lg" href="/reserve">
            Private Events
          </Button>
        </motion.div>
      </motion.div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════
   PAGE
   ═══════════════════════════════════════════════════════ */
export default function HomePage() {
  return (
    <>
      <HeroSection />
      <PhilosophySection />
      <MenuPreviewSection />
      <ChefSection />
      <FarmNumbersSection />
      <TestimonialSection />
      <GallerySection />
      <MarqueeSection />
      <LocationsSection />
      <ReservationCTASection />
    </>
  );
}
