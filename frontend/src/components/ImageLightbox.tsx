import "./ImageLightbox.css";

interface ImageLightboxProps {
  src: string;
  alt: string;
  title?: string;
  onClose: () => void;
}

export default function ImageLightbox({ src, alt, title, onClose }: ImageLightboxProps) {
  return (
    <div className="image-lightbox-overlay" onClick={onClose}>
      <div className="image-lightbox-dialog" onClick={(event) => event.stopPropagation()}>
        <header className="image-lightbox-header">
          <span>{title ?? alt}</span>
          <button type="button" className="image-lightbox-close" onClick={onClose}>
            关闭
          </button>
        </header>
        <img className="image-lightbox-img" src={src} alt={alt} />
      </div>
    </div>
  );
}
