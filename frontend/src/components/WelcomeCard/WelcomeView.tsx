import logo from "../../assets/scrap-logo.svg";
import { Doodles } from "../Doodles/Doodles";
import "./WelcomeCard.css";

/** Default page view: margin sketches plus the taped welcome sheet. */
export function WelcomeView() {
  return (
    <>
      <Doodles />
      <div className="welcome-paper">
        <span className="tape" aria-hidden="true" />
        <section className="welcome-card" aria-label="Welcome to SCRAP">
          <div className="logo-tile">
            <img src={logo} alt="" />
          </div>
          <h1 className="welcome-title">
            Welcome to <span className="accent">SCRAP</span>
          </h1>
          <p className="welcome-acronym">
            <b>S</b>ingle-<b>c</b>ell <b>R</b>NA-seq <b>A</b>nalysis <b>P</b>ipeline
          </p>
          <p className="welcome-subtitle">
            Your AI research assistant for analyzing <span className="underlined">RNA-seq data.</span>
          </p>
          <p className="welcome-description">Ask a question, upload a dataset, or start a new analysis.</p>
        </section>
      </div>
    </>
  );
}
