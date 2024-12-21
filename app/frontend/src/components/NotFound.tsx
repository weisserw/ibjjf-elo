import yuriImage from '/src/assets/yuri.jpg'
import "./NotFound.css"

function NotFound() {
  return (
    <section className="is-fullheight">
      <div className="hero-body">
        <div className="container has-text-centered">
          <h1 className="title">
            Page Not Found
          </h1>
          <h2 className="subtitle">
            You have confused Yuri
          </h2>
          <div>
            <img src={yuriImage} className="yuri" alt="Yuri" height="300" />
          </div>
          <a className="is-light" href="/">
            Go Back Home
          </a>
        </div>
      </div>
    </section>
  )
}

export default NotFound