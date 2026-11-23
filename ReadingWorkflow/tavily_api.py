import logging
from concurrent.futures import ThreadPoolExecutor
from tavily import TavilyClient


logger = logging.getLogger(__name__)


class TavilySearcher:
    def __init__(self, api_key: str, max_results: int = 1): # 너무 크면 gemini 에게 자료 건넬 때 터짐.
        if not api_key:
            raise ValueError("Tavily API 설정이 필요합니다.")

        if max_results < 1:
            raise ValueError("max_results는 1 이상이어야 합니다.")

        self.client = TavilyClient(api_key=api_key)
        self.max_results = max_results
        
    # 각 주제별로 최신기사 tavily 로 검색해서 반환.
    def search_latest_articles(self, categories: list[str]) -> list[dict]:

        def search_category(category):
            try:
                return self._search(
                    f'{category} 관련 최신 기사 1개'
                )
            except Exception as exc:
                logger.warning(
                    "Tavily 검색 실패 [%s]: %s",
                    category, exc
                )
                return []

        with ThreadPoolExecutor(max_workers=5) as executor:
            results = executor.map(search_category, categories)

        return [
            article
            for result in results
            for article in (result or [])
        ]




    def search_related_articles(self, search_query: str) -> list[dict]:
        
        search_query = search_query.strip()

        if not search_query:
            return []

        try:
            search_results = self._search(search_query)

            if not search_results:
                return []

            urls = self._collect_urls(search_results)

            if not urls:
                return []

            extracted_results = self._extract_articles(urls)

            return self._merge_results(
                search_results,
                extracted_results,
            )

        except Exception as exc:
            logger.warning(
                "Tavily 검색/추출 실패: %s",
                exc,
            )
            return []

    def _search(self, query: str) -> list[dict]:
        response = self.client.search(
            query=query,
            topic="news",
            search_depth="advanced",
            time_range="year",
            max_results=self.max_results,
            include_answer=False,
        )

        return [
            result
            for result in response.get("results", [])
            if isinstance(result, dict)
        ]

    @staticmethod
    def _collect_urls(results: list[dict]) -> list[str]:
        return list(
            dict.fromkeys(
                result["url"]
                for result in results
                if isinstance(result.get("url"), str)
                and result["url"].strip()
            )
        )

    def _extract_articles(self, urls: list[str]) -> list[dict]:
        if not urls:
            return []

        response = self.client.extract(
            urls=urls,
            extract_depth="advanced",
            format="markdown",
        )

        return [
            result
            for result in response.get("results", [])
            if isinstance(result, dict)
        ]

    @staticmethod
    def _merge_results(search_results: list[dict], extracted_results: list[dict]) -> list[dict]:

        search_by_url = {
            result["url"]: result
            for result in search_results
            if isinstance(result.get("url"), str)
        }

        articles = []
        seen_urls = set()

        for extracted in extracted_results:
            url = extracted.get("url")
            content = extracted.get("raw_content")

            if not isinstance(url, str) or url in seen_urls:
                continue

            if not isinstance(content, str) or not content.strip():
                continue

            search_result = search_by_url.get(url, {})

            title = (
                search_result.get("title")
                or extracted.get("title")
            )

            if not isinstance(title, str) or not title.strip():
                continue

            articles.append(
                {
                    "title": title.strip(),
                    "url": url,
                    "published_date": search_result.get(
                        "published_date"
                    ),
                    "content": content.strip(),
                    "relevance_score": search_result.get("score"),
                }
            )

            seen_urls.add(url)

        return articles