"use client";

import Link from "next/link";
import { IconMapPin, IconClock, IconPhone, IconBrandInstagram } from "@tabler/icons-react";

export default function Footer() {
  return (
    <footer className="bg-charcoal text-cream/60 border-t border-cream/5">
      <div className="max-w-7xl mx-auto px-6 py-16">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-12">
          {/* Brand */}
          <div>
            <span
              className="text-cream font-bold text-2xl block mb-4"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Maison Verte
            </span>
            <p className="text-sm leading-relaxed mb-4" style={{ fontFamily: "var(--font-body)" }}>
              A seasonal restaurant rooted in our 12-acre Hillsboro farm. Two locations in Portland, Oregon.
            </p>
            <a href="#" className="hover:text-cream transition-colors" aria-label="Instagram">
              <IconBrandInstagram size={20} />
            </a>
          </div>

          {/* Pearl District */}
          <div>
            <h4
              className="text-cream text-lg mb-4"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Pearl District
            </h4>
            <ul className="space-y-3 text-sm" style={{ fontFamily: "var(--font-body)" }}>
              <li className="flex items-start gap-2">
                <IconMapPin size={16} className="mt-0.5 shrink-0 text-amber" />
                <span>412 NW 13th Ave, Portland, OR 97209</span>
              </li>
              <li className="flex items-start gap-2">
                <IconClock size={16} className="mt-0.5 shrink-0 text-amber" />
                <span>Tue-Sun 5:00pm - 10:00pm</span>
              </li>
              <li className="flex items-start gap-2">
                <IconPhone size={16} className="mt-0.5 shrink-0 text-amber" />
                <span>(503) 555-0142</span>
              </li>
            </ul>
          </div>

          {/* Alberta Arts */}
          <div>
            <h4
              className="text-cream text-lg mb-4"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Alberta Arts District
            </h4>
            <ul className="space-y-3 text-sm" style={{ fontFamily: "var(--font-body)" }}>
              <li className="flex items-start gap-2">
                <IconMapPin size={16} className="mt-0.5 shrink-0 text-amber" />
                <span>2817 NE Alberta St, Portland, OR 97211</span>
              </li>
              <li className="flex items-start gap-2">
                <IconClock size={16} className="mt-0.5 shrink-0 text-amber" />
                <span>Wed-Sun 5:30pm - 10:30pm</span>
              </li>
              <li className="flex items-start gap-2">
                <IconPhone size={16} className="mt-0.5 shrink-0 text-amber" />
                <span>(503) 555-0198</span>
              </li>
            </ul>
          </div>

          {/* Navigation */}
          <div>
            <h4
              className="text-cream text-lg mb-4"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Explore
            </h4>
            <ul className="space-y-2 text-sm" style={{ fontFamily: "var(--font-body)" }}>
              <li>
                <Link href="/menu" className="hover:text-cream transition-colors">
                  Seasonal Menu
                </Link>
              </li>
              <li>
                <Link href="/farm" className="hover:text-cream transition-colors">
                  Our Farm
                </Link>
              </li>
              <li>
                <Link href="/reserve" className="hover:text-cream transition-colors">
                  Reservations
                </Link>
              </li>
              <li>
                <a href="#" className="hover:text-cream transition-colors">
                  Private Events
                </a>
              </li>
              <li>
                <a href="#" className="hover:text-cream transition-colors">
                  Gift Cards
                </a>
              </li>
            </ul>
          </div>
        </div>

        <div className="border-t border-cream/10 pt-8 flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-sm">&copy; 2026 Maison Verte. All rights reserved.</p>
          <div className="flex gap-6 text-sm">
            <a href="#" className="hover:text-cream transition-colors">
              Privacy Policy
            </a>
            <a href="#" className="hover:text-cream transition-colors">
              Terms of Service
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}
