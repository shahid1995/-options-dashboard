// StrikeNova Public Design System — Barrel Export

// Legacy exports (existing components)
export { default as PublicLayout } from "./PublicLayout";
export { default as PublicHeader } from "./PublicHeader";
export { default as PublicFooter } from "./PublicFooter";
export { default as SectionHeading } from "./SectionHeading";
export { default as FeatureCard } from "./FeatureCard";
export { default as CTASection } from "./CTASection";
export { default as DemoMetric } from "./DemoMetric";
export { default as AuthModal } from "./AuthModal";
export { default as AuthModalProvider, useAuthModal } from "./AuthModalContext";
export { PUBLIC_CSS, PAGE_MAX, sectionPad, DEMO_LABEL_STYLE } from "./styles";

// V1.2 Design System Primitives
export { COLOR, TYPE, SPACE, RADIUS, SHADOW, LAYER, BREAKPOINT, MOTION, DATA_STATE, RESEARCH_STATUS } from "./tokens";
export { PUBLIC_DS_CSS, fadeUpStyle, signalGlowStyle, traceDrawStyle } from "./motion";
export { Surface, Panel, MetricPanel, OutlinePanel, SignalPanel } from "./surfaces";
export { Button, LinkButton, TextLink } from "./buttons";
export { Metric, formatMetricValue } from "./Metric";
export { VisualizationFrame } from "./VisualizationFrame";
export { SignalLine, SignalNode, StrikeRail, DataTrace, TechnicalDivider, GridOverlay } from "./signals";
export { Section, Container, TwoColumn, MetricGrid, CardGrid, BentoGrid, FlexRow, FlexColumn, Asymmetric } from "./layout";
export { DemoLabel, ResearchBadge, DataStateBadge, Eyebrow, SectionTitle } from "./truth";
export { SignalField, DEMO_SIGNAL_STATE } from "./SignalField";
