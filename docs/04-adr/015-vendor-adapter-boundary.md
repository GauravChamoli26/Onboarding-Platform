# ADR-015: Every integration behind an adapter interface

**Status:** Accepted
**Date:** 2026-08-30
**Decision Log ref:** D-05, D-06, and SDD §3.0

## Context

Twelve integrations, several of which are unsettled: the voice AI vendor is deferred, the BGV vendor needs a parallel pilot before contracting, LinkedIn is manual now and might have an API later, and Gifteko is first-party but customers may want their own gifting supplier.

Vendor SDKs called directly from module code make every one of those changes a rewrite.

## Decision

Every external integration sits behind an internal adapter interface. Module code never touches a vendor SDK.

Consequences that follow directly:

- **BGV** ships with a manual-entry adapter at launch; AuthBridge and SpringVerify implement the same interface and plug in when contracted
- **Voice AI** is deferred with Layer 1 and Layer 2 interfaces preserved; reintroduction is an implementation plus a flag
- **Kit dispatch** treats Gifteko as the default implementation of `KitDispatchProvider`, not the only one
- The AuthBridge/SpringVerify parallel pilot runs through production integration code

Every vendor-dependent stage is additionally skippable by feature flag, with the skip recorded on the candidate timeline.

## Consequences

Scope decisions become configuration rather than rework. That property is what made deferring voice, deferring the BGV contract, and shipping kit dispatch first-party all cheap decisions instead of architectural ones.

Uniform cross-cutting concerns: signature verification on inbound webhooks, retry with backoff, circuit breakers, region assertion, and PII minimisation are implemented once at the adapter layer rather than per vendor.

The cost is an indirection layer over every integration, including ones unlikely to change. Accepted — the ones we were confident about are not the ones that moved.

With Gifteko as a separate legal entity, the adapter boundary is also the sub-processor boundary, which makes the minimal payload a compliance property rather than a design preference.

## Alternatives considered

**Direct SDK calls where the vendor is settled** — less code, and it would have made deferring voice and splitting the BGV module from its vendor into rewrites rather than configuration.
