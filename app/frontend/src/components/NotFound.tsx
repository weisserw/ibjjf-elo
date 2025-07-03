import yuriImage from '/src/assets/yuri.jpg'
import "./NotFound.css"

function NotFound() {
  return (
    <section className="section has-background-light py-0" style={{ minHeight: '100vh' }}>
      <div className="container">
        <div className="box" style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)', borderRadius: '12px' }}>
          <div className="hero-body">
            <div className="container has-text-centered">
              <h1 className="title is-spaced">
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
        </div>
      </div>
    </section>
  )
}

export default NotFound