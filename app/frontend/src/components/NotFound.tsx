import yuriImage from '/src/assets/yuri.jpg'
import { useAppContext } from "../AppContext";
import { t } from "../translate";

import "./NotFound.css"

function NotFound() {
  useAppContext();

  return (
    <section className="is-fullheight">
      <div className="hero-body">
        <div className="container has-text-centered">
          <h1 className="title is-spaced">
            {t("Page Not Found")}
          </h1>
          <h2 className="subtitle">
            {t("You have confused Yuri")}
          </h2>
          <div>
            <img src={yuriImage} className="yuri" alt="Yuri" height="300" />
          </div>
          <a className="is-light" href="/">
            {t("Go Back Home")}
          </a>
        </div>
      </div>
    </section>
  )
}

export default NotFound