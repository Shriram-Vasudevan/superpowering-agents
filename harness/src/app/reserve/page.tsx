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
import {
  IconCalendar,
  IconClock,
  IconUsers,
  IconMapPin,
  IconPhone,
  IconMessage,
} from "@tabler/icons-react";
import Button from "@/components/Button";

/* ─── Images ─── */
const IMAGES = {
  FOOD_1: "https://images.unsplash.com/photo-1690299564210-ff855826b278?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_3: "https://images.unsplash.com/photo-1660505465468-c898ea7ff674?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwzfHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_5: "https://images.unsplash.com/photo-1771573042846-9f3631a48058?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw1fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_6: "https://images.unsplash.com/photo-1658041133672-17552737d6d3?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw2fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_7: "https://images.unsplash.com/photo-1692197275441-40c874f40385?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw3fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_8: "https://images.unsplash.com/photo-1626200419884-427c1108bc27?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw5fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_9: "https://images.unsplash.com/photo-1676037150408-4b59a542fa7c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw4fHxnb3VybWV0JTIwcGxhdGVkJTIwZGlzaCUyMGZpbmUlMjBkaW5pbmclMjBzZWFzb25hbCUyMHZlZ2V0YWJsZXMlMjBlbGVnYW50JTIwcHJlc2VudGF0aW9ufGVufDF8MHx8fDE3NzQ1NzU4Mjl8MA&ixlib=rb-4.1.0&q=80&w=1080",
  FOOD_10: "https://images.unsplash.com/photo-1587207850226-ba5ac4c96c9c?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxMHx8Z291cm1ldCUyMHBsYXRlZCUyMGRpc2glMjBmaW5lJTIwZGluaW5nJTIwc2Vhc29uYWwlMjB2ZWdldGFibGVzJTIwZWxlZ2FudCUyMHByZXNlbnRhdGlvbnxlbnwxfDB8fHwxNzc0NTc1ODI5fDA&ixlib=rb-4.1.0&q=80&w=1080",
  INTERIOR_1: "https://images.unsplash.com/photo-1761116183308-6a23c287a605?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHwxfHxmYXJtJTIwdG8lMjB0YWJsZSUyMHJlc3RhdXJhbnQlMjBpbnRlcmlvciUyMGNhbmRsZWxpdCUyMHdhcm0lMjBtb29keSUyMGV2ZW5pbmclMjBkaW5pbmd8ZW58MXwwfHx8MTc3NDU3NTgyOHww&ixlib=rb-4.1.0&q=80&w=1080",
  CHEF_5: "https://images.unsplash.com/photo-1697020358336-3db2f502242a?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4ODc4Mzd8MHwxfHNlYXJjaHw1fHxjaGVmJTIwY29va2luZyUyMGtpdGNoZW4lMjBwcm9mZXNzaW9uYWwlMjBkYXJrJTIwbW9vZHklMjBjdWxpbmFyeXxlbnwxfDB8fHwxNzc0NTc1ODM0fDA&ixlib=rb-4.1.0&q=85",
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
function ReserveHero() {
  return (
    <Section className="relative min-h-[70vh] flex items-center overflow-hidden bg-[#0f0f0f] noise-overlay">
      {/* Oversized watermark */}
      <div
        className="absolute top-16 left-1/2 -translate-x-1/2 text-[12rem] leading-none font-bold pointer-events-none select-none mix-blend-soft-light"
        style={{
          fontFamily: "var(--font-display)",
          WebkitTextStroke: "1px oklch(0.96 0.02 80 / 0.06)",
          color: "transparent",
        }}
        aria-hidden
      >
        RESERVE
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6 w-full py-24">
        <div className="flex flex-col md:flex-row items-end gap-16">
          <div className="md:w-[55%]">
            <div className="overflow-hidden mb-6">
              <motion.h1
                variants={textRevealClip}
                className="text-4xl sm:text-5xl text-cream font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Your Table Awaits
              </motion.h1>
            </div>
            <motion.div variants={fadeUpChild}>
              <div className="w-24 h-[2px] bg-amber" />
            </motion.div>
          </div>

          <motion.div
            variants={blurScaleIn}
            className="md:w-[40%] relative h-[350px] md:translate-y-16 grain-overlay"
          >
            <Image
              src={IMAGES.FOOD_1}
              alt="Plated dish"
              fill
              className="object-cover grayscale-[30%] warm-tone"
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
   SECTION 2 — RESERVATION FORM
   ═══════════════════════════════════════════════════════ */
function ReservationFormSection() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const y = useTransform(scrollYProgress, [0, 1], [-30, 30]);

  return (
    <Section className="relative bg-cream py-32 overflow-hidden noise-overlay">
      <div className="relative z-10 max-w-7xl mx-auto px-6">
        <div className="flex flex-col md:flex-row gap-16 items-start">
          {/* Form */}
          <motion.div
            variants={blurScaleIn}
            className="md:w-[60%] bg-warm-white shadow-lg p-10"
          >
            <h2
              className="text-3xl text-charcoal mb-8 font-light"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Make a Reservation
            </h2>

            <form className="space-y-6" onSubmit={(e) => e.preventDefault()}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <div>
                  <label
                    className="text-charcoal/60 text-sm mb-2 block"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    Date
                  </label>
                  <div className="relative">
                    <IconCalendar size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-charcoal/30" />
                    <input
                      type="date"
                      className="w-full border border-amber/30 bg-transparent pl-10 pr-4 py-3 text-charcoal rounded-none focus:outline-none focus:border-amber"
                      style={{ fontFamily: "var(--font-body)" }}
                    />
                  </div>
                </div>

                <div>
                  <label
                    className="text-charcoal/60 text-sm mb-2 block"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    Time
                  </label>
                  <div className="relative">
                    <IconClock size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-charcoal/30" />
                    <select
                      className="w-full border border-amber/30 bg-transparent pl-10 pr-4 py-3 text-charcoal rounded-none focus:outline-none focus:border-amber appearance-none"
                      style={{ fontFamily: "var(--font-body)" }}
                    >
                      <option>5:00 PM</option>
                      <option>5:30 PM</option>
                      <option>6:00 PM</option>
                      <option>6:30 PM</option>
                      <option>7:00 PM</option>
                      <option>7:30 PM</option>
                      <option>8:00 PM</option>
                      <option>8:30 PM</option>
                      <option>9:00 PM</option>
                      <option>9:30 PM</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label
                    className="text-charcoal/60 text-sm mb-2 block"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    Party Size
                  </label>
                  <div className="relative">
                    <IconUsers size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-charcoal/30" />
                    <select
                      className="w-full border border-amber/30 bg-transparent pl-10 pr-4 py-3 text-charcoal rounded-none focus:outline-none focus:border-amber appearance-none"
                      style={{ fontFamily: "var(--font-body)" }}
                    >
                      {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
                        <option key={n}>{n} {n === 1 ? "Guest" : "Guests"}</option>
                      ))}
                      <option>9+ Guests (Private Dining)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label
                    className="text-charcoal/60 text-sm mb-2 block"
                    style={{ fontFamily: "var(--font-body)" }}
                  >
                    Location
                  </label>
                  <div className="relative">
                    <IconMapPin size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-charcoal/30" />
                    <select
                      className="w-full border border-amber/30 bg-transparent pl-10 pr-4 py-3 text-charcoal rounded-none focus:outline-none focus:border-amber appearance-none"
                      style={{ fontFamily: "var(--font-body)" }}
                    >
                      <option>Pearl District</option>
                      <option>Alberta Arts District</option>
                    </select>
                  </div>
                </div>
              </div>

              <div>
                <label
                  className="text-charcoal/60 text-sm mb-2 block"
                  style={{ fontFamily: "var(--font-body)" }}
                >
                  Special Requests
                </label>
                <div className="relative">
                  <IconMessage size={18} className="absolute left-3 top-4 text-charcoal/30" />
                  <textarea
                    rows={4}
                    placeholder="Dietary restrictions, celebrations, seating preferences..."
                    className="w-full border border-amber/30 bg-transparent pl-10 pr-4 py-3 text-charcoal rounded-none focus:outline-none focus:border-amber resize-none placeholder:text-charcoal/30"
                    style={{ fontFamily: "var(--font-body)" }}
                  />
                </div>
              </div>

              <Button variant="solid" size="lg" shimmer className="w-full">
                Reserve Your Table
              </Button>
            </form>
          </motion.div>

          {/* Right photo */}
          <motion.div
            ref={ref}
            variants={blurScaleIn}
            className="md:w-[40%] relative h-[500px] md:h-[650px] overflow-hidden"
          >
            <motion.div style={{ y }} className="absolute inset-[-30px] grain-overlay vignette">
              <Image
                src={IMAGES.CHEF_5}
                alt="Chef cooking"
                fill
                className="object-cover warm-tone"
                sizes="(max-width: 768px) 100vw, 40vw"
              />
            </motion.div>
          </motion.div>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 3 — ATMOSPHERE GALLERY (Embla)
   ═══════════════════════════════════════════════════════ */
function AtmosphereGallery() {
  const [emblaRef] = useEmblaCarousel({ loop: true, align: "start" });
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const x = useTransform(scrollYProgress, [0, 1], [-30, 30]);

  const photos = [
    { src: IMAGES.FOOD_1, filter: "warm-tone" },
    { src: IMAGES.FOOD_3, filter: "sepia-filter" },
    { src: IMAGES.FOOD_5, filter: "warm-tone" },
    { src: IMAGES.FOOD_6, filter: "sepia-filter" },
    { src: IMAGES.FOOD_7, filter: "warm-tone" },
    { src: IMAGES.FOOD_8, filter: "sepia-filter" },
    { src: IMAGES.FOOD_9, filter: "warm-tone" },
    { src: IMAGES.FOOD_10, filter: "sepia-filter" },
  ];

  return (
    <section ref={ref} className="relative bg-[#0a0a0a] py-24 overflow-hidden">
      {/* Oversized watermark */}
      <div
        className="absolute top-12 right-8 text-[14rem] leading-none font-bold pointer-events-none select-none"
        style={{
          fontFamily: "var(--font-display)",
          WebkitTextStroke: "1px oklch(0.96 0.02 80 / 0.05)",
          color: "transparent",
        }}
        aria-hidden
      >
        DINE
      </div>

      <div className="relative z-10">
        <motion.div style={{ x }} className="overflow-hidden" ref={emblaRef}>
          <div className="flex gap-4">
            {photos.map((photo, i) => (
              <div
                key={i}
                className="relative flex-[0_0_40%] min-w-[280px] h-[70vh] grain-overlay"
              >
                <Image
                  src={photo.src}
                  alt={`Atmosphere ${i + 1}`}
                  fill
                  className={`object-cover ${photo.filter}`}
                  sizes="40vw"
                />
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 4 — PRIVATE EVENTS
   ═══════════════════════════════════════════════════════ */
function PrivateEventsSection() {
  return (
    <Section className="relative py-32 overflow-hidden noise-overlay">
      {/* Background */}
      <div className="absolute inset-0">
        <Image
          src={IMAGES.INTERIOR_1}
          alt="Dining interior"
          fill
          className="object-cover warm-tone"
          sizes="100vw"
        />
        <div className="absolute inset-0 bg-[#0f0f0f]/55 mix-blend-multiply" />
        <div className="absolute inset-0 grain-overlay" />
      </div>

      {/* Oversized watermark */}
      <div
        className="absolute top-8 right-8 text-[16rem] leading-none font-bold pointer-events-none select-none"
        style={{
          fontFamily: "var(--font-display)",
          WebkitTextStroke: "1px oklch(0.96 0.02 80 / 0.06)",
          color: "transparent",
        }}
        aria-hidden
      >
        120
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6">
        <motion.h2
          variants={fadeUpChild}
          className="text-4xl sm:text-5xl lg:text-6xl text-cream mb-16 font-light"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Private Events &<br />Celebrations
        </motion.h2>

        <div className="flex flex-col md:flex-row gap-8">
          {/* Large card: Full Buyout */}
          <motion.div
            variants={blurScaleIn}
            className="md:w-[60%] bg-charcoal/90 border border-amber/20 p-10"
          >
            <span
              className="text-amber text-xs tracking-[0.3em] uppercase block mb-4"
              style={{ fontFamily: "var(--font-body)" }}
            >
              Full Buyout
            </span>
            <h3
              className="text-3xl text-cream mb-4 font-light"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Up to 120 Guests
            </h3>
            <p
              className="text-cream/60 text-sm leading-relaxed mb-6"
              style={{ fontFamily: "var(--font-body)" }}
            >
              Transform the entire restaurant into your private venue. Custom menus, dedicated service team, full bar program. Ideal for weddings, corporate events, and milestone celebrations.
            </p>
            <Button variant="solid" size="lg" shimmer>
              Plan Your Event
            </Button>
          </motion.div>

          {/* Right: stacked smaller cards */}
          <div className="md:w-[40%] flex flex-col gap-6">
            <motion.div
              variants={fadeUpChild}
              className="border border-cream/10 p-8"
            >
              <span
                className="text-amber text-xs tracking-[0.3em] uppercase block mb-3"
                style={{ fontFamily: "var(--font-body)" }}
              >
                Intimate Dinner
              </span>
              <h3
                className="text-2xl text-cream mb-2 font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Up to 12 Guests
              </h3>
              <p
                className="text-cream/50 text-sm"
                style={{ fontFamily: "var(--font-body)" }}
              >
                Chef&apos;s table experience with custom tasting menu.
              </p>
            </motion.div>

            <motion.div
              variants={fadeUpChild}
              className="border border-cream/10 p-8"
            >
              <span
                className="text-amber text-xs tracking-[0.3em] uppercase block mb-3"
                style={{ fontFamily: "var(--font-body)" }}
              >
                Private Room
              </span>
              <h3
                className="text-2xl text-cream mb-2 font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Up to 40 Guests
              </h3>
              <p
                className="text-cream/50 text-sm"
                style={{ fontFamily: "var(--font-body)" }}
              >
                Dedicated dining room with bespoke menu options.
              </p>
            </motion.div>
          </div>
        </div>
      </div>
    </Section>
  );
}

/* ═══════════════════════════════════════════════════════
   SECTION 5 — FIND US
   ═══════════════════════════════════════════════════════ */
function FindUsSection() {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start end", "end start"],
  });
  const y = useTransform(scrollYProgress, [0, 1], [-30, 30]);

  return (
    <Section className="relative bg-cream py-32 overflow-hidden noise-overlay">
      <div className="relative z-10 max-w-7xl mx-auto px-6">
        <motion.h2
          variants={fadeUpChild}
          className="text-4xl sm:text-5xl text-charcoal mb-16 font-light"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Find Us
        </motion.h2>

        <div className="flex flex-col md:flex-row gap-8 items-start">
          {/* Left: large photo with overlaid card */}
          <motion.div
            variants={blurScaleIn}
            ref={ref}
            className="md:w-[60%] relative"
          >
            <div className="relative h-[450px] overflow-hidden">
              <motion.div style={{ y }} className="absolute inset-[-30px] grain-overlay">
                <Image
                  src={IMAGES.FOOD_3}
                  alt="Pearl District location"
                  fill
                  className="object-cover sepia-filter"
                  sizes="(max-width: 768px) 100vw, 60vw"
                />
              </motion.div>
            </div>

            {/* Overlapping card */}
            <div className="bg-warm-white shadow-lg p-8 -mt-16 mx-6 relative z-10">
              <h3
                className="text-2xl text-charcoal mb-4 font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Pearl District
              </h3>
              <ul
                className="space-y-3 text-charcoal/60 text-sm"
                style={{ fontFamily: "var(--font-body)" }}
              >
                <li className="flex items-start gap-2">
                  <IconMapPin size={16} className="mt-0.5 shrink-0 text-forest" />
                  <span>412 NW 13th Ave, Portland, OR 97209</span>
                </li>
                <li className="flex items-start gap-2">
                  <IconClock size={16} className="mt-0.5 shrink-0 text-forest" />
                  <span>Tue&ndash;Sun, 5:00pm &ndash; 10:00pm</span>
                </li>
                <li className="flex items-start gap-2">
                  <IconPhone size={16} className="mt-0.5 shrink-0 text-forest" />
                  <span>(503) 555-0142</span>
                </li>
              </ul>
              <div className="mt-4">
                <Button variant="underline" size="sm">
                  Get Directions
                </Button>
              </div>
            </div>
          </motion.div>

          {/* Right: smaller photo + card */}
          <motion.div
            variants={blurScaleIn}
            className="md:w-[40%]"
          >
            <div className="relative h-[350px] grain-overlay">
              <Image
                src={IMAGES.FOOD_10}
                alt="Alberta Arts location"
                fill
                className="object-cover warm-tone"
                sizes="(max-width: 768px) 100vw, 40vw"
              />
            </div>
            <div className="bg-warm-white shadow-lg p-8">
              <h3
                className="text-2xl text-charcoal mb-4 font-light"
                style={{ fontFamily: "var(--font-display)" }}
              >
                Alberta Arts District
              </h3>
              <ul
                className="space-y-3 text-charcoal/60 text-sm"
                style={{ fontFamily: "var(--font-body)" }}
              >
                <li className="flex items-start gap-2">
                  <IconMapPin size={16} className="mt-0.5 shrink-0 text-forest" />
                  <span>2817 NE Alberta St, Portland, OR 97211</span>
                </li>
                <li className="flex items-start gap-2">
                  <IconClock size={16} className="mt-0.5 shrink-0 text-forest" />
                  <span>Wed&ndash;Sun, 5:30pm &ndash; 10:30pm</span>
                </li>
                <li className="flex items-start gap-2">
                  <IconPhone size={16} className="mt-0.5 shrink-0 text-forest" />
                  <span>(503) 555-0198</span>
                </li>
              </ul>
              <div className="mt-4">
                <Button variant="underline" size="sm">
                  Get Directions
                </Button>
              </div>
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
export default function ReservePage() {
  return (
    <>
      <ReserveHero />
      <ReservationFormSection />
      <AtmosphereGallery />
      <PrivateEventsSection />
      <FindUsSection />
    </>
  );
}
