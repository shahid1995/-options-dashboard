# Content Contract: Evidence & Trust Section

## Static Content Definition

**File**: `frontend/components/public/EvidenceTrustContent.js`

```javascript
export const evidenceTrustContent = {
  eyebrow: "EVIDENCE & TRUST",
  title: "Built on evidence. Not guarantees.",
  description: "StrikeNova turns market data into structured analytical workflows for Indian index options (NIFTY). All outputs are designed to support your decision-making process, not to predict the future.",
  points: [
    {
      title: "Decision-Support, Not Decision-Making",
      body: "StrikeNova provides analytical layers and quant tools to help you evaluate market conditions. The final trading decision is always yours."
    },
    {
      title: "Paper Trading Only",
      body: "All execution simulation within StrikeNova is paper-only. No real capital is at risk when you use this platform."
    },
    {
      title: "Transparency Over Hype",
      body: "StrikeNova exposes its analytical methods, assumptions, and limitations. We prefer you understand the tool deeply over trusting it blindly."
    },
    {
      title: "Uncertainty Is Inherent",
      body: "Options markets are inherently uncertain. No analytical framework eliminates risk. Past analytical outputs do not guarantee future outcomes."
    }
  ],
  disclaimer: "StrikeNova is an educational and research tool. It does not provide financial advice. All paper-trading simulations are hypothetical and may differ from actual market conditions.",
  ctaLabel: "Learn More About StrikeNova",
  ctaHref: "/about"
};
```

## Contract Constraints

- Content must NOT be modified to claim guaranteed accuracy
- Content must NOT imply live trading capability without explicit authorization
- Content must NOT remove or weaken the uncertainty/risk disclaimer
- Content must NOT add new points without corresponding spec update
- `ctaHref` must point to an existing public route
