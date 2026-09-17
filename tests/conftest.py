from collections.abc import Callable
from typing import Any

import pytest

from harvester.config import JobConfig

BASE = "https://shop.test/catalogue/"

PAGE_1 = """
<html><body>
  <article class="product_pod">
    <h3><a href="book-1.html" title="A Light in the Attic">A Light in the ...</a></h3>
    <p class="price_color">£51.77</p>
    <p class="instock availability">
        In   stock
    </p>
    <p class="star-rating Three"></p>
    <a class="tag">poetry</a><a class="tag">classic</a>
  </article>
  <article class="product_pod">
    <h3><a href="book-2.html" title="Tipping the Velvet">Tipping the ...</a></h3>
    <p class="price_color">£53.74</p>
    <p class="instock availability">In stock</p>
    <p class="star-rating One"></p>
  </article>
  <article class="product_pod"><!-- broken card, no title -->
    <p class="price_color">£1.00</p>
  </article>
  <ul class="pager"><li class="next"><a href="page-2.html">next</a></li></ul>
</body></html>
"""

PAGE_2 = """
<html><body>
  <article class="product_pod">
    <h3><a href="book-3.html" title="Soumission">Soumission</a></h3>
    <p class="price_color">£50.10</p>
    <p class="instock availability">In stock</p>
    <p class="star-rating Five"></p>
  </article>
  <ul class="pager"><li class="next"><a href="page-1.html">back to start</a></li></ul>
</body></html>
"""

JobFactory = Callable[..., JobConfig]


def job_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "books",
        "start_urls": [BASE + "page-1.html"],
        "item": "article.product_pod",
        "fields": {
            "title": {"selector": "h3 a", "attr": "title", "required": True},
            "price": "p.price_color | price",
            "availability": "p.instock | strip",
            "rating": r"p.star-rating @class | regex:star-rating (\w+) | lower",
            "url": "h3 a @href | absolute_url",
        },
        "pagination": {"next": "li.next a", "max_pages": 5},
        "http": {"rate_limit": None, "backoff": 0, "retries": 2},
    }
    data.update(overrides)
    return data


@pytest.fixture
def make_job() -> JobFactory:
    def factory(**overrides: Any) -> JobConfig:
        return JobConfig.model_validate(job_data(**overrides))

    return factory
