"use client";

import { useRef } from "react";
import Image from "next/image";
import {
  motion,
  useInView,
  useScroll,
  useTransform,
} from "framer-motion";
import { IconArrowRight } from "@tabler/icons-react";
import Button from "@/components/Button";

/* ─── Images ─── */
const IMAGES = {
  FOOD_2: "https://images.unsplash.com/photo-1766736590783-2636257e79ba?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwyfHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_7: "https://images.unsplash.com/photo-1692197275441-40c874f40385?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw3fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_8: "https://images.unsplash.com/photo-1626200419884-427c1108bc27?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw5fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_9: "https://images.unsplash.com/photo-1676037150408-4b59a542fa7c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw4fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
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
function MenuHero() {
  return (
    <Section className="relative min-h-[80vh] flex items-end overflow-hidden">
      {/* Background */}
      <div className="absolute inset-0">
        <Image
          src={IMAGES.FOOD_2}
          alt="Seasonal dishes"
          fill
          className="object-cover warm-tone high-contrast"
          sizes="100vw"
          priority
        />
        <div className="absolute inset-0 bg-charcoal/40 mix-blend-multiply" />
        <div className="absolute inset-0 grain-overlay" />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6 pb-24 pt-48 w-full">
        <div className="flex flex-col md:flex-row items-end justify-between gap-8">
          <div>
            <div className="overflow-hidden">
              <motion.h1
                variants={textRevealClip}
                className="text-6xl sm:text-7xl lg:text-9xl text-cream font-light mix-blend-difference"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Seasonal Menu
              </motion.h1>
            </div>
          </div>
          <motion.p
            variants={fadeUpChild}
            className="text-cream/70 text-lg max-w-sm text-right"
            style={{ fontFamily: "var(--font-body)" }}
          >
            Spring 2026 &mdash; From Our Hillsboro Farm
          </motion.p>
        </div>

        {/* Chef's note overlap card */}
        <motion.div
          variants={blurScaleIn}
          className="mt-8 bg-charcoal/90 border border-amber/20 p-8 max-w-xl -mb-16 relative z-20"
        >
          <span
            className="text-amber text-sm tracking-[0.3em] uppercase block mb-3"
            style={{ fontFamily: "var(--font-body)" }}
          >
            Chef&apos;s Note
          </span>
          <p
            className="text-cream/70 text-sm leading-relaxed"
            style={{ fontFamily: "var(--font-body)" }}
          >
            Our menu changes with every harvest. What you see today reflects what our land gave us this week. We work with the seasons, never against them.
          </p>
        </motion.div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 2 — FIRST COURSE
   ═══════════════════════════════════════════════════════ */
function FirstCourseSection() {
  const dishes = [
    { name: "Nettle & Leek Soup with Cr\u00e8me Fra\u00eeche", price: "$16" },
    { name: "Spring Pea Risotto with Mint & Pecorino", price: "$18" },
    { name: "Roasted Beet Salad with Ch\u00e8vre & Hazelnuts", price: "$17" },
    { name: "Dungeness Crab Cake with Preserved Lemon Aioli", price: "$22" },
    { name: "Seared Diver Scallops with Cauliflower Pur\u00e9e", price: "$24", featured: true },
    { name: "House-Smoked Trout with Pickled Ramps", price: "$19" },
    { name: "Burrata with Heirloom Tomato & Basil", price: "$16" },
    { name: "Wild Mushroom Tartlet with Thyme Cream", price: "$18" },
  ];

  return (
    <Section className="relative bg-cream py-32 pt-48 overflow-hidden noise-overlay">
      {/* Oversized watermark */}
      <div
        className="absolute top-16 right-8 text-[20rem] leading-none font-bold text-charcoal/[0.03] pointer-events-none select-none"
        style={{ fontFamily: "var(--font-display)" }}
        aria-hidden
      >
        01
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6">
        <motion.h2
          variants={fadeUpChild}
          className="text-4xl sm:text-5xl text-charcoal mb-16 font-light"
          style={{ fontFamily: "var(--font-display)" }}
        >
          First Course
        </motion.h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-16 gap-y-2">
          {dishes.map((dish) =>
            dish.featured ? (
              <motion.div
                key={dish.name}
                variants={blurScaleIn}
                className="md:col-span-2 bg-warm-white shadow-lg flex flex-col md:flex-row my-6"
              >
                <div className="relative h-[300px] md:h-auto md:w-[45%] grain-overlay">
                  <Image
                    src={IMAGES.FOOD_9}
                    alt={dish.name}
                    fill
                    className="object-cover warm-tone"
                    sizes="(max-width: 768px) 100vw, 45vw"
                  />
                </div>
                <div className="p-8 md:w-[55%] flex flex-col justify-center">
                  <span
                    className="text-amber text-xs tracking-[0.3em] uppercase block mb-2"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    Featured
                  </span>
                  <h3
                    className="text-2xl text-charcoal mb-2 font-light"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {dish.name}
                  </h3>
                  <p
                    className="text-charcoal/50 text-sm mb-4"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    Hand-dived scallops from the Oregon coast, seared until golden, atop a silky cauliflower pur&eacute;e with brown butter and capers.
                  </p>
                  <span
                    className="text-forest text-xl"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {dish.price}
                  </span>
                </div>
              </motion.div>
            ) : (
              <motion.div
                key={dish.name}
                variants={fadeUpChild}
                className="flex items-baseline justify-between py-4 border-b border-charcoal/10"
              >
                <span
                  className="text-lg text-charcoal font-light"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {dish.name}
                </span>
                <span
                  className="text-forest text-lg ml-4 shrink-0"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {dish.price}
                </span>
              </motion.div>
            )
          )}
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 3 — MAIN COURSE
   ═══════════════════════════════════════════════════════ */
function MainCourseSection() {
  const dishes = [
    { name: "Pan-Seared Copper River Salmon with Spring Vegetables", price: "$38" },
    { name: "Braised Lamb Shank with Root Vegetable Pur\u00e9e", price: "$42", featured: true },
    { name: "Grilled Heritage Pork Chop with Stone Fruit Mostarda", price: "$36" },
    { name: "Pan-Roasted Duck Breast with Cherry Gastrique", price: "$44" },
    { name: "Wild King Salmon with Nettle Beurre Blanc", price: "$40" },
    { name: "Grass-Fed Ribeye with Bone Marrow Butter", price: "$52" },
    { name: "Forest Mushroom Ragout with Soft Polenta", price: "$28" },
    { name: "Whole Roasted Trout with Brown Butter & Capers", price: "$34" },
  ];

  return (
    <Section className="relative bg-[#1a1a1a] py-32 overflow-hidden noise-overlay">
      {/* Oversized watermark */}
      <div
        className="absolute top-16 right-8 text-[20rem] leading-none font-bold text-cream/[0.03] pointer-events-none select-none"
        style={{ fontFamily: "var(--font-display)" }}
        aria-hidden
      >
        02
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6">
        <motion.h2
          variants={fadeUpChild}
          className="text-4xl sm:text-5xl text-cream mb-16 font-light"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Main Course
        </motion.h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-16 gap-y-2">
          {dishes.map((dish) =>
            dish.featured ? (
              <motion.div
                key={dish.name}
                variants={blurScaleIn}
                className="md:col-span-2 bg-charcoal-light shadow-lg flex flex-col md:flex-row my-6"
              >
                <div className="relative h-[300px] md:h-auto md:w-[45%] grain-overlay">
                  <Image
                    src={IMAGES.FOOD_7}
                    alt={dish.name}
                    fill
                    className="object-cover warm-tone"
                    sizes="(max-width: 768px) 100vw, 45vw"
                  />
                </div>
                <div className="p-8 md:w-[55%] flex flex-col justify-center">
                  <span
                    className="text-amber text-xs tracking-[0.3em] uppercase block mb-2"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    Featured
                  </span>
                  <h3
                    className="text-2xl text-cream mb-2 font-light"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {dish.name}
                  </h3>
                  <p
                    className="text-cream/50 text-sm mb-4"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    Slow-braised for eight hours until fork-tender, served over a silky root vegetable pur&eacute;e with rosemary jus and roasted baby carrots from our farm.
                  </p>
                  <span
                    className="text-amber text-xl"
                    style={{ fontFamily: "var(--font-display)" }}
                  >
                    {dish.price}
                  </span>
                </div>
              </motion.div>
            ) : (
              <motion.div
                key={dish.name}
                variants={fadeUpChild}
                className="flex items-baseline justify-between py-4 border-b border-cream/10"
              >
                <span
                  className="text-lg text-cream font-light"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {dish.name}
                </span>
                <span
                  className="text-amber text-lg ml-4 shrink-0"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {dish.price}
                </span>
              </motion.div>
            )
          )}
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 4 — DESSERTS & BEVERAGES (split)
   ═══════════════════════════════════════════════════════ */
function DessertsAndBeveragesSection() {
  const desserts = [
    { name: "Rhubarb Pavlova", price: "$14" },
    { name: "Dark Chocolate Terrine", price: "$16" },
    { name: "Seasonal Fruit Galette", price: "$13" },
    { name: "Vanilla Bean Cr\u00e8me Br\u00fbl\u00e9e", price: "$14" },
    { name: "Cheese Board (3 selections)", price: "$22" },
    { name: "Lavender Honey Panna Cotta", price: "$13" },
  ];

  const drinks = [
    { name: "Willamette Valley Pinot Noir (glass)", price: "$18" },
    { name: "Eola-Amity Hills Chardonnay", price: "$16" },
    { name: "Portland Negroni", price: "$16" },
    { name: "Elderflower Spritz", price: "$14" },
    { name: "Farm Herb Gimlet", price: "$15" },
    { name: "Seasonal Shrub Mocktail", price: "$10" },
    { name: "Pear Brandy Old Fashioned", price: "$18" },
    { name: "Oregon Pinot Gris", price: "$15" },
  ];

  return (
    <Section className="relative overflow-hidden">
      <div className="flex flex-col md:flex-row">
        {/* Left: Desserts on cream */}
        <div className="md:w-[45%] bg-cream py-24 px-8 md:px-12 relative noise-overlay">
          <div className="relative z-10">
            <motion.h2
              variants={fadeUpChild}
              className="text-3xl sm:text-4xl text-charcoal mb-12 font-light"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Desserts
            </motion.h2>
            {desserts.map((item) => (
              <motion.div
                key={item.name}
                variants={fadeUpChild}
                className="flex items-baseline justify-between py-3 border-b border-charcoal/10"
              >
                <span
                  className="text-charcoal font-light"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {item.name}
                </span>
                <span
                  className="text-forest ml-4 shrink-0"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {item.price}
                </span>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Center: overlapping photo */}
        <motion.div
          variants={blurScaleIn}
          className="hidden md:block relative w-[10%] z-20"
        >
          <div className="absolute top-1/2 -translate-y-1/2 -left-[120px] w-[240px] h-[340px] grain-overlay">
            <Image
              src={IMAGES.FOOD_8}
              alt="Cheese board"
              fill
              className="object-cover warm-tone"
              sizes="240px"
            />
          </div>
        </motion.div>

        {/* Right: Drinks on dark */}
        <div className="md:w-[55%] bg-[#1a1a1a] py-24 px-8 md:px-12 relative noise-overlay">
          <div className="relative z-10">
            <motion.h2
              variants={fadeUpChild}
              className="text-3xl sm:text-4xl text-cream mb-12 font-light"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Wine & Cocktails
            </motion.h2>
            {drinks.map((item) => (
              <motion.div
                key={item.name}
                variants={fadeUpChild}
                className="flex items-baseline justify-between py-3 border-b border-cream/10"
              >
                <span
                  className="text-cream font-light"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {item.name}
                </span>
                <span
                  className="text-amber ml-4 shrink-0"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  {item.price}
                </span>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 5 — PRIVATE DINING CTA
   ═══════════════════════════════════════════════════════ */
function PrivateDiningCTA() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const y = useTransform(scrollYProgress, [0, 1], [-30, 30]);

  return (
    <Section className="relative min-h-[80vh] flex items-center overflow-hidden">
      <div ref={ref} className="absolute inset-0 overflow-hidden">
        <motion.div style={{ y }} className="absolute inset-[-40px]">
          <Image
            src={IMAGES.INTERIOR_1}
            alt="Private dining room"
            fill
            className="object-cover warm-tone"
            sizes="100vw"
          />
        </motion.div>
        <div className="absolute inset-0 bg-charcoal/35 mix-blend-multiply" />
        <div className="absolute inset-0 grain-overlay" />
        <div className="absolute inset-0 vignette" />
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
                Host Your
                <br />
                Next Event
              </motion.h2>
            </div>
          </div>

          <motion.div
            variants={blurScaleIn}
            className="md:w-[40%] bg-charcoal/90 border border-amber/20 p-10"
          >
            <ul
              className="space-y-4 text-cream/70 text-lg"
              style={{ fontFamily: "var(--font-body)" }}
            >
              <li className="flex items-center gap-3">
                <span className="w-2 h-2 bg-amber shrink-0" />
                Intimate dinners for 12
              </li>
              <li className="flex items-center gap-3">
                <span className="w-2 h-2 bg-amber shrink-0" />
                Private room for 40
              </li>
              <li className="flex items-center gap-3">
                <span className="w-2 h-2 bg-amber shrink-0" />
                Full buyout for 120
              </li>
            </ul>
            <p
              className="text-amber mt-6 text-sm"
              style={{ fontFamily: "var(--font-body)" }}
            >
              Starting at $85/person
            </p>
            <div className="mt-8">
              <Button variant="solid" size="lg" shimmer href="/reserve">
                Inquire Now
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
export default function MenuPage() {
  return (
    <>
      <MenuHero />
      <FirstCourseSection />
      <MainCourseSection />
      <DessertsAndBeveragesSection />
      <PrivateDiningCTA />
    </>
  );
}
