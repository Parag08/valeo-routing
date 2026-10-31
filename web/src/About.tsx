import { useEffect, useRef } from "react";

/** The real story behind the demo. The only real figures in the app live here, each with its status. */
export function About({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog ref={ref} className="about" onClose={onClose} aria-labelledby="about-title"
            onClick={(e) => e.target === ref.current && onClose()}>
      <div className="about-body">
        <div className="about-head">
          <h2 id="about-title">About this rebuild</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">Close</button>
        </div>

        <p>
          In summer 2026 Parag was a management intern at <b>Valeo Health</b>, a UAE home-healthcare provider. Nurse–driver pairs
          drive to patients' homes for short visits: sample collection, IV therapy and injections. Orders arrive on a partner
          booking platform and are claimed by whichever provider moves first. Ops claimed them by hand in Excel, and idle pairs
          waited at the office between visits.
        </p>
        <p>
          He built <b>Logistics Valeo</b>, the dispatch tool ops ran the field-visit line on: an acceptance engine that claims
          what the fleet can serve, a live day view, roster auto-allocation, standby hubs, capacity and metrics. It went live on
          1 August 2026. The first days had many issues; daily catch-ups with ops for 14 days fixed them, and ops moved fully onto
          the tool within a week. The auto-accept lead time moved from 3 h to 24 h after ops pushed back, and night hours stopped
          counting.
        </p>

        <h3>Measured results <span className="pill real">Real</span></h3>
        <table className="about-results">
          <tbody>
            <tr><td>Orders captured from the platform</td><td><b>60–70% → 80–90%</b></td><td>Validated by the ops lead</td></tr>
            <tr><td>Field-visit km per order</td><td><b>60 → 45.3 km (−24.6%)</b></td><td>16 Aug–16 Sep, 29 clean days; 42.6 km in September</td></tr>
            <tr><td>Distance saved</td><td><b>~23,000 km a month</b></td><td>At that month's order volume</td></tr>
            <tr><td>Cost saved</td><td><b>~AED 12,400 a month</b></td><td>At the marginal cost per km; accepted by the company</td></tr>
          </tbody>
        </table>
        <p className="hint">
          Caveat: daily order volume rose over the same period, and denser days cost less per order. How much of the drop came
          from hubs and how much from volume was not separated, so the claim is "km per order fell about 25% after launch",
          not "hubs cut km by 25%".
        </p>

        <h3>What is real here and what is synthetic</h3>
        <ul>
          <li><b>Real:</b> the problem, the seven screens, the rules ops worked by, and the results above.</li>
          <li><b>Synthetic:</b> every order, patient, nurse, driver, hub and number on the other screens, generated from a seed
            over public neighbourhood centroids. The code is written fresh; nothing comes from Valeo's systems.</li>
          <li>The demo's gaps between policies are not tuned to match the real ones. They move the same way for the same reasons.</li>
        </ul>

        <h3>What was left unbuilt</h3>
        <ul>
          <li><b>v2 swap-out</b> was designed but not shipped. It runs here behind the policy switch, labelled as such.</li>
          <li><b>Home nursing and babysitting</b> got no routing tool on purpose: ops already paired 86% of shift changeovers and
            93% of movements repeat day to day, so an optimiser had little left to win.</li>
          <li>Not modelled in the demo: live disruptions during the day, hub bays and hub kit supply, and a road router (predictions
            use straight-line distance × a road factor, as the original did).</li>
        </ul>
      </div>
    </dialog>
  );
}
