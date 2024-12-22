import {ReactNode} from "react";
import classNames from "classnames";
import "./DBPagination.css";

interface PaginationProps {
  page: number
  totalPages: number
  onPageClick: (page: number, event: React.MouseEvent<HTMLAnchorElement>) => void
  onPreviousPage: (event: React.MouseEvent<HTMLAnchorElement>) => void
  onNextPage: (event: React.MouseEvent<HTMLAnchorElement>) => void
}

function DBPagination({page, totalPages, onPageClick, onPreviousPage, onNextPage}: PaginationProps) {
  const renderPageLink = (pageNumber: number) => {
    return (
      <li>
        <a href="#" className={classNames("pagination-link", {"is-current": page === pageNumber})} onClick={(event) => onPageClick(pageNumber, event)}>
          {pageNumber}
        </a>
      </li>
    );
  }

  const renderEllipsis = () => {
    return (
      <li>
        <span className="pagination-ellipsis">&hellip;</span>
      </li>
    );
  }

  const elements: ReactNode[] = [];
  elements.push(renderPageLink(1));
  if (page !== 1 && page !== totalPages) {
    if (page - 1 > 2) {
      elements.push(renderEllipsis());
    }
    if (page - 1 > 1) {
      elements.push(renderPageLink(page - 1));
    }
    elements.push(renderPageLink(page));
    if (page + 1 < totalPages) {
      elements.push(renderPageLink(page + 1));
    }
    if (page + 1 < totalPages - 1) {
      elements.push(renderEllipsis());
    }
  } else if (page === 1) {
    if (totalPages > 2) {
      elements.push(renderPageLink(2));
    }
    if (totalPages > 3) {
      elements.push(renderEllipsis());
    }
  } else if (page === totalPages) {
    if (totalPages > 3) {
      elements.push(renderEllipsis());
    }
    if (totalPages > 2) {
      elements.push(renderPageLink(totalPages - 1));
    }
  }
  if (totalPages > 1) {
    elements.push(renderPageLink(totalPages));
  }

  return (
    <nav className="pagination pagination-margin" role="navigation">
      <a href="#" className={classNames("pagination-previous", {"is-disabled": page === 1})} onClick={onPreviousPage}>Previous</a>
      <a href="#" className={classNames("pagination-next", {"is-disabled": page === totalPages})} onClick={onNextPage}>Next</a>
      <ul className="pagination-list">
        {elements}
      </ul>
    </nav>
  );
}

export default DBPagination;
