import difflib
import re
from django.db.models import Q
from quotes.models import QuoteRequest, QuoteItem
from django.core.cache import cache
import json


def is_mobile(request):
    """Check if request is from mobile device"""
    return any(
        x in request.META.get("HTTP_USER_AGENT", "").lower()
        for x in ["mobile", "android", "iphone", "ipad"]
    )


def normalize_description(description):
    """Normalize a description for better matching"""
    # Convert to lowercase
    text = description.lower()

    # Remove punctuation
    text = re.sub(r"[^\w\s]", " ", text)

    # Replace multiple spaces with single space
    text = re.sub(r"\s+", " ", text)

    # Common word substitutions
    substitutions = {
        "curvomark": "curve o mark",
        "comb": "combination",
        "eng": "engineer",
        "engeneering": "engineer",
        "pein": "pin",
        "leel": "level",  # Typo fix
    }

    for original, replacement in substitutions.items():
        text = text.replace(original, replacement)

    return text.strip()


def attempt_quote_matching(order):
    """
    Attempts to find and link a matching quote to an order
    Returns: tuple (success, matched_quote, confidence)
    """
    print(f"[DEBUG] Matching order #{order.order_number} (ID: {order.id})")

    if order.quote:
        print("[DEBUG] Order already has a quote linked")
        return False, None, 0

    # Only look at completed or processed quotes for this company
    potential_quotes = QuoteRequest.objects.filter(
        Q(status="processed")
        | Q(status="complete")
        | Q(status="approved")
        | Q(status="emailed"),
        customer__company=order.company,
    ).order_by("-created_at")[:50]

    print(
        f"[DEBUG] Found {potential_quotes.count()} potential quotes for company {order.company.company}"
    )

    if not potential_quotes:
        order.quote_matching_attempted = True
        order.save(update_fields=["quote_matching_attempted"])
        return False, None, 0

    best_quote = None
    best_score = 0

    # Get order items
    order_items = order.items.all()
    print(f"[DEBUG] Order has {order_items.count()} items")

    matched_items = []

    # Expanded list of common hardware words to ignore in matching
    common_hardware_terms = [
        "with",
        "from",
        "this",
        "that",
        "stainless",
        "steel",
        "black",
        "blue",
        "red",
        "green",
        "size",
        "inch",
        "inches",
        "meter",
        "type",
        "model",
        "part",
        "parts",
        "item",
        "unit",
        "package",
        "pack",
        "piece",
        "pieces",
        "product",
        "hardware",
        "tool",
        "tools",
        "series",
        "grade",
        "quality",
        "brand",
        "high",
        "heavy",
        "duty",
        "standard",
        "industrial",
        "commercial",
        "width",
        "length",
        "body",
    ]

    # Product category terms that should be considered critical differentiators
    product_categories = {
        # Fasteners
        "bolt": "threaded_fastener",
        "screw": "threaded_fastener",
        "nut": "threaded_fastener",
        "washer": "fastener_accessory",
        "anchor": "anchoring_fastener",
        "nail": "impact_fastener",
        "rivet": "permanent_fastener",
        "stud": "threaded_fastener",
        "cap": "threaded_fastener",
        "allen": "threaded_fastener",
        "hex": "threaded_fastener",
        "socket": "threaded_fastener",
        # Security items
        "lock": "security",
        "padlock": "security",
        "key": "security",
        # Tools
        "pump": "fluid_handling",
        "gun": "application_tool",
        "drill": "rotary_tool",
        "saw": "cutting_tool",
        "hammer": "impact_tool",
        "wrench": "hand_tool",
        "screwdriver": "hand_tool",
        "grinder": "abrasive_tool",
        "brush": "cleaning_tool",
        "plier": "gripping_tool",
        # Consumables
        "grease": "lubricant",
        "oil": "lubricant",
        "glue": "adhesive",
        "threadlock": "adhesive",
        "loctite": "adhesive",
        "disc": "abrasive",
        "cutting": "abrasive",
        "sandpaper": "abrasive",
        # Power equipment
        "compressor": "pneumatic",
        "pneumatic": "pneumatic",
        "charger": "power",
        "battery": "power",
    }

    # Function to extract size information
    def extract_size(text):
        # Look for metric sizes like M8, M10, M12
        metric_matches = re.findall(r"M(\d+)", text, re.IGNORECASE)
        if metric_matches:
            return [f"M{m}" for m in metric_matches]

        # Look for dimensions like 20x30, 10mm, etc.
        dimension_matches = re.findall(r"(\d+)(?:\s*[xX]\s*\d+|\s*mm|\s*cm|\s*m)", text)
        if dimension_matches:
            return dimension_matches

        return []

    for quote in potential_quotes:
        print(f"[DEBUG] Testing quote #{quote.quote_number}")
        # Initialize score for this quote
        score = 0
        quote_matches = []

        # Get quote items
        quote_items = quote.items.all()
        print(f"[DEBUG] Quote has {quote_items.count()} items")

        # Special handling for quotes with lots of matching prices
        exact_price_matches_map = {}  # Will store matches by price

        # First, check for price matches across all items
        for order_item in order_items:
            if not order_item.selling_price:
                continue

            order_price = float(order_item.selling_price)

            for quote_item in quote_items:
                if not quote_item.selling_price:
                    continue

                quote_price = float(quote_item.selling_price)

                # EXACT price match (to the penny)
                if abs(order_price - quote_price) < 0.01:
                    if order_price not in exact_price_matches_map:
                        exact_price_matches_map[order_price] = []

                    exact_price_matches_map[order_price].append(
                        {"order_item": order_item, "quote_item": quote_item}
                    )

        # Count unique prices that match
        unique_price_matches = len(exact_price_matches_map.keys())
        total_matched_items = sum(
            len(matches) for matches in exact_price_matches_map.values()
        )

        print(
            f"[DEBUG] Found {unique_price_matches} unique price matches ({total_matched_items} items total)"
        )

        # STRONG MATCH: If most items have exact price matches
        if (
            unique_price_matches >= 5
            and order_items
            and (unique_price_matches / len(order_items)) >= 0.5
        ):
            print(
                f"[DEBUG] Strong price-based match detected! {unique_price_matches} unique prices match exactly"
            )

            # Automatically consider this a high-confidence match
            score = 80
            matched_count = total_matched_items

            # Create match details for the UI
            quote_matches = []
            for price, matches in exact_price_matches_map.items():
                for match in matches:
                    quote_matches.append(
                        {
                            "order_id": match["order_item"].id,
                            "order_desc": match["order_item"].description.lower(),
                            "quote_desc": match["quote_item"].description.lower(),
                            "match_score": 90,
                            "match_reason": f"Exact price match (R {price})",
                            "quantity": match["quote_item"].quantity,
                            "order_quantity": match["order_item"].quantity,
                            "quote_price": float(match["quote_item"].selling_price),
                            "order_price": float(match["order_item"].selling_price),
                            "common_terms": [],
                            "order_categories": [],
                            "quote_categories": [],
                            "order_sizes": [],
                            "quote_sizes": [],
                            "supplier_match": False,
                        }
                    )

            # Skip the normal matching process and go directly to storing the result
            best_score = score
            best_quote = quote
            matched_items = quote_matches
            print(
                f"[DEBUG] Auto-matched by price: Quote #{quote.quote_number} with score {score}"
            )
            continue  # Skip to next quote

        # SPECIAL CASE: Flashback arrestors and similar industrial items with rearranged words
        # Match if they have identical prices, quantities, and key terms regardless of word order
        common_industrial_terms = {
            "flashback": [
                "arrestor",
                "regulator",
                "torch",
                "oxygen",
                "acetylene",
                "end",
                "side",
            ],
            "regulator": ["pressure", "valve", "control", "gas", "flow"],
            "welding": ["torch", "tip", "nozzle", "gas", "mig", "tig"],
            "fitting": ["connector", "coupling", "adapter", "union", "tee", "elbow"],
            "hose": ["pipe", "tube", "connector", "clamp", "oxygen", "acetylene"],
        }

        # If regular matching isn't finding matches, try a more flexible industrial matching approach
        if unique_price_matches >= 2 and (
            len(order_items) > 0 and len(quote_items) > 0
        ):
            industrial_matches = 0
            industrial_match_details = []

            for order_item in order_items:
                # Skip items without prices
                if not order_item.selling_price:
                    continue

                order_desc = order_item.description.lower().strip()
                order_price = float(order_item.selling_price or 0)
                order_qty = order_item.quantity

                # Find key industrial terms in the order
                order_key_terms = set()
                for key, related_terms in common_industrial_terms.items():
                    if key in order_desc:
                        order_key_terms.add(key)
                        for term in related_terms:
                            if term in order_desc:
                                order_key_terms.add(term)

                if len(order_key_terms) < 2:  # Need at least 2 key terms to match
                    continue

                # Find potential matches in quote items
                for quote_item in quote_items:
                    if not quote_item.selling_price:
                        continue

                    quote_desc = quote_item.description.lower().strip()
                    quote_price = float(quote_item.selling_price or 0)
                    quote_qty = quote_item.quantity

                    # Skip if prices don't match (allow 2% difference)
                    if (
                        abs(order_price - quote_price) / max(order_price, quote_price)
                        > 0.02
                    ):
                        continue

                    # Skip if quantities don't match
                    if order_qty != quote_qty:
                        continue

                    # Check for key terms overlap
                    quote_key_terms = set()
                    for key, related_terms in common_industrial_terms.items():
                        if key in quote_desc:
                            quote_key_terms.add(key)
                            for term in related_terms:
                                if term in quote_desc:
                                    quote_key_terms.add(term)

                    # Count overlapping terms
                    common_terms = order_key_terms.intersection(quote_key_terms)

                    # If we have good term overlap with matching price and quantity,
                    # this is very likely the same item
                    if len(common_terms) >= 2:
                        industrial_matches += 1
                        industrial_match_details.append(
                            {
                                "order_id": order_item.id,
                                "order_desc": order_desc,
                                "quote_desc": quote_desc,
                                "match_score": 85,
                                "match_reason": f"Industrial item match: matching price, quantity, and {len(common_terms)} key terms",
                                "quantity": quote_qty,
                                "order_quantity": order_qty,
                                "quote_price": quote_price,
                                "order_price": order_price,
                                "common_terms": list(common_terms),
                                "order_categories": [],
                                "quote_categories": [],
                                "order_sizes": [],
                                "quote_sizes": [],
                                "supplier_match": False,
                            }
                        )

            # If we found enough industrial matches, consider it a good match
            if (
                industrial_matches >= 2
                and (industrial_matches / len(order_items)) >= 0.5
            ):
                print(
                    f"[DEBUG] Industrial item match detected! {industrial_matches} items match price, quantity and key terms"
                )

                # Set a high confidence score
                industrial_score = 75 + min(
                    industrial_matches * 2, 15
                )  # Base 75 plus up to 15 more based on match count

                # Skip normal matching and use these results
                best_score = industrial_score
                best_quote = quote
                matched_items = industrial_match_details
                print(
                    f"[DEBUG] Industrial match: Quote #{quote.quote_number} with score {industrial_score}"
                )
                continue  # Skip to next quote

        # Start with item quantity matching
        if len(quote_items) == len(order_items):
            score += 10  # Reduced from 20 to 10
            print(f"[DEBUG] +10 points for matching item count")
        elif abs(len(quote_items) - len(order_items)) <= 2:
            score += 5  # Reduced from 10 to 5
            print(f"[DEBUG] +5 points for close item count")

        # Compare each order item against each quote item
        matched_count = 0
        price_match_count = 0
        exact_matches = 0
        quantity_match_count = 0
        supplier_match_count = 0

        for order_item in order_items:
            best_match = None
            best_match_score = 0
            best_match_details = None

            order_desc = order_item.description.lower().strip()

            # Extract key terms - important words from the order description
            order_key_terms = set(
                [
                    term
                    for term in order_desc.split()
                    if len(term) > 3 and term not in common_hardware_terms
                ]
            )

            # Identify product categories in order item
            order_categories = set()
            for term, category in product_categories.items():
                if term in order_desc:
                    order_categories.add(category)

            # Extract size information
            order_sizes = extract_size(order_desc)

            # Clean up order description
            clean_order_desc = re.sub(r"\([^)]*\)", "", order_desc).strip()

            # Check for model numbers (alphanumeric patterns)
            order_model_numbers = re.findall(
                r"[a-zA-Z]\d+(?:[a-zA-Z0-9-]*[a-zA-Z0-9])?", order_desc
            )
            order_model_numbers = [
                m.upper() for m in order_model_numbers if len(m) >= 3
            ]

            # Temporary fix to disable supplier matching entirely
            order_supplier = None

            for quote_item in quote_items:
                quote_desc = quote_item.description.lower().strip()

                # Extract key terms from quote
                quote_key_terms = set(
                    [
                        term
                        for term in quote_desc.split()
                        if len(term) > 3 and term not in common_hardware_terms
                    ]
                )

                # Identify product categories in quote item
                quote_categories = set()
                for term, category in product_categories.items():
                    if term in quote_desc:
                        quote_categories.add(category)

                # Extract size information
                quote_sizes = extract_size(quote_desc)

                # Check for model numbers
                quote_model_numbers = re.findall(
                    r"[a-zA-Z]\d+(?:[a-zA-Z0-9-]*[a-zA-Z0-9])?", quote_desc
                )
                quote_model_numbers = [
                    m.upper() for m in quote_model_numbers if len(m) >= 3
                ]

                # Temporary fix to disable supplier matching entirely
                quote_supplier = None

                # Check for category mismatch - if both have categories and they don't overlap
                category_mismatch = (
                    len(order_categories) > 0
                    and len(quote_categories) > 0
                    and not order_categories.intersection(quote_categories)
                )

                # Check for size mismatch - if both have sizes and they don't match
                size_mismatch = (
                    len(order_sizes) > 0
                    and len(quote_sizes) > 0
                    and not set(order_sizes).intersection(set(quote_sizes))
                )

                # Check for model number match
                model_match = any(
                    om == qm for om in order_model_numbers for qm in quote_model_numbers
                )

                # And comment out the supplier match calculation
                supplier_match = False  # Disabled temporarily: order_supplier and quote_supplier and order_supplier == quote_supplier

                # Calculate key term overlap
                common_terms = order_key_terms.intersection(quote_key_terms)

                # STRICT MATCHING: Early rejection for mismatches on critical attributes

                # If categories mismatch, still proceed but with lower confidence
                if (
                    category_mismatch
                    and len(order_categories) >= 1
                    and len(quote_categories) >= 1
                ):
                    # Instead of immediate rejection, apply a penalty
                    match_score = 0
                    print(
                        f"[DEBUG] Category mismatch but proceeding: {order_categories} vs {quote_categories}"
                    )
                    # Don't continue - allow it to proceed to price matching

                # If sizes mismatch (like M12 vs M20)
                if size_mismatch and not (
                    len(order_sizes) == 0 or len(quote_sizes) == 0
                ):
                    match_score = 0
                    match_reason = f"Size mismatch: {order_sizes} vs {quote_sizes}"
                    continue

                # Now proceed with the matching logic

                # Special case: EXACT price match is VERY strong evidenc

                # Special case: EXACT price match is VERY strong evidence
                if order_item.selling_price and quote_item.selling_price:
                    # Check for exact price match (to the penny)
                    if (
                        abs(
                            float(order_item.selling_price)
                            - float(quote_item.selling_price)
                        )
                        < 0.01
                    ):
                        # Significant boost for exact price - this is extremely unlikely to be coincidence
                        match_score = 80
                        match_reason = f"Exact price match ({order_item.selling_price})"

                        # If quantities also match, it's almost certainly the same item
                        if order_item.quantity == quote_item.quantity:
                            match_score = 90
                            match_reason += " + Quantity match"

                # Only proceed if we have some meaningful term overlap or a model match
                if len(common_terms) > 0 or model_match or supplier_match:
                    # First try direct match (case insensitive)
                    if order_desc == quote_desc:
                        match_score = 100
                        match_reason = "Exact match"

                    # Model number is a very strong indicator
                    elif model_match:
                        match_score = 80
                        match_reason = f"Model number match: {','.join(set(order_model_numbers).intersection(quote_model_numbers))}"

                    # Try matching after removing parentheses content
                    elif (
                        clean_order_desc
                        and clean_order_desc
                        == re.sub(r"\([^)]*\)", "", quote_desc).strip()
                    ):
                        match_score = 90
                        match_reason = "Match after removing parentheses"

                    # If quote desc has a hyphen, try matching with part after hyphen
                    elif " - " in quote_desc:
                        parts = quote_desc.split(" - ", 1)
                        after_hyphen = parts[1].strip()

                        if order_desc == after_hyphen:
                            match_score = 85
                            match_reason = "Exact match with part after hyphen"
                        else:
                            # Try difflib sequence matcher with after hyphen part
                            ratio = difflib.SequenceMatcher(
                                None, order_desc, after_hyphen
                            ).ratio()
                            # Only consider if ratio is high enough
                            if ratio > 0.7:  # Increased from 0.6 to 0.7
                                match_score = ratio * 70
                                match_reason = f"Sequence match with part after hyphen ({ratio:.2f})"
                            else:
                                match_score = 0
                                match_reason = "Below threshold"

                    # Try regular sequence matcher for everything else - but require higher similarity
                    else:
                        order_desc_normalized = normalize_description(
                            order_item.description
                        )
                        quote_desc_normalized = normalize_description(
                            quote_item.description
                        )
                        similarity = difflib.SequenceMatcher(
                            None, order_desc_normalized, quote_desc_normalized
                        ).ratio()
                        # Only consider if ratio is high enough (0.7 = 70% similar) - raised from 0.6
                        if similarity > 0.7:
                            match_score = similarity * 60
                            match_reason = f"Sequence match ({similarity:.2f})"
                        else:
                            match_score = 0
                            match_reason = "Below threshold"
                else:
                    # No common key terms, so assign a zero score
                    match_score = 0
                    match_reason = "No common key terms"

                # Supplier match is a very strong indicator
                if match_score > 0 and supplier_match:
                    match_score += 25  # Higher bonus for supplier match
                    match_reason += " + Same supplier"

                # Exact price match is a strong indicator
                if (
                    match_score > 0
                    and order_item.selling_price
                    and quote_item.selling_price
                ):
                    price_ratio = min(
                        float(order_item.selling_price), float(quote_item.selling_price)
                    ) / max(
                        float(order_item.selling_price), float(quote_item.selling_price)
                    )

                    # If prices are very close (within 2%), boost match score significantly
                    if price_ratio > 0.98:
                        match_score += 30
                        match_reason += " + Exact price match"
                    # If prices are somewhat close (within 10%), boost score moderately
                    elif price_ratio > 0.90:
                        match_score += 15
                        match_reason += f" + Close price match ({price_ratio:.2f})"

                # Exact quantity match is also important
                if match_score > 0:
                    if order_item.quantity == quote_item.quantity:
                        match_score += 20
                        match_reason += " + Quantity match"
                    else:
                        # Penalize quantity mismatch more heavily - increased from 10 to 20
                        match_score -= 20
                        match_reason += f" - Quantity mismatch ({order_item.quantity} vs {quote_item.quantity})"

                # If this is the best match so far for this order item
                if match_score > best_match_score:
                    best_match_score = match_score
                    best_match = quote_item
                    best_match_details = {
                        "order_id": order_item.id,
                        "order_desc": order_desc,
                        "quote_desc": quote_desc,
                        "match_score": match_score,
                        "match_reason": match_reason,
                        "quantity": quote_item.quantity,
                        "order_quantity": order_item.quantity,
                        "quote_price": (
                            float(quote_item.selling_price)
                            if quote_item.selling_price
                            else None
                        ),
                        "order_price": (
                            float(order_item.selling_price)
                            if order_item.selling_price
                            else None
                        ),
                        "common_terms": (
                            list(common_terms) if len(common_terms) > 0 else []
                        ),
                        "order_categories": list(order_categories),
                        "quote_categories": list(quote_categories),
                        "order_sizes": order_sizes,
                        "quote_sizes": quote_sizes,
                        "supplier_match": supplier_match,
                    }

            # If we found a decent match for this order item
            if best_match and best_match_score >= 70:  # Raised threshold from 60 to 70
                matched_count += 1
                quote_matches.append(best_match_details)
                print(
                    f"[DEBUG] Found match for item: {best_match_details['match_reason']} ({best_match_score:.1f}%)"
                )

                # Count exact matches (90%+ score)
                if best_match_score >= 90:
                    exact_matches += 1

                # Count quantity matches
                if order_item.quantity == best_match.quantity:
                    quantity_match_count += 1

                # Count price matches
                if order_item.selling_price and best_match.selling_price:
                    price_ratio = min(
                        float(order_item.selling_price), float(best_match.selling_price)
                    ) / max(
                        float(order_item.selling_price), float(best_match.selling_price)
                    )
                    if price_ratio > 0.90:  # Within 10%
                        price_match_count += 1

                # Count supplier matches
                supplier_match_count = 0

        # Calculate percentage of matched items and add to score
        if order_items:
            match_percentage = (matched_count / len(order_items)) * 100
            score += min(match_percentage, 30)  # Reduced from 40 to 30
            print(
                f"[DEBUG] +{min(match_percentage, 30):.1f} points from matched items ({matched_count}/{len(order_items)})"
            )

            # Bonus for exact matches
            exact_match_percentage = (exact_matches / len(order_items)) * 100
            score += min(
                exact_match_percentage, 20
            )  # Add up to 20 points for exact matches
            print(
                f"[DEBUG] +{min(exact_match_percentage, 20):.1f} points from exact matches ({exact_matches}/{len(order_items)})"
            )

            # Add bonus for quantity matches
            qty_match_percentage = (quantity_match_count / len(order_items)) * 100
            score += min(qty_match_percentage, 15)  # Reduced from 20 to 15
            print(
                f"[DEBUG] +{min(qty_match_percentage, 15):.1f} points from quantity matches ({quantity_match_count}/{len(order_items)})"
            )

            # Add bonus for supplier matches - heavily weighted
            supplier_match_percentage = (supplier_match_count / len(order_items)) * 100
            score += min(
                supplier_match_percentage, 25
            )  # Up to 25 points for supplier matches
            print(
                f"[DEBUG] +{min(supplier_match_percentage, 25):.1f} points from supplier matches ({supplier_match_count}/{len(order_items)})"
            )

            # Add bonus for price matches
            price_match_percentage = (price_match_count / len(order_items)) * 100
            score += min(price_match_percentage, 15)  # Reduced from 20 to 15
            print(
                f"[DEBUG] +{min(price_match_percentage, 15):.1f} points from price matches ({price_match_count}/{len(order_items)})"
            )

        # Special case: Multiple exact price matches indicate a very strong match
        exact_price_matches = 0
        for order_item in order_items:
            for quote_item in quote_items:
                if (
                    order_item.selling_price
                    and quote_item.selling_price
                    and abs(
                        float(order_item.selling_price)
                        - float(quote_item.selling_price)
                    )
                    < 0.01
                ):
                    exact_price_matches += 1

        # If we have many exact price matches, this is VERY strong evidence
        if exact_price_matches >= 3 and (exact_price_matches / len(order_items)) >= 0.5:
            print(
                f"[DEBUG] Boosting confidence due to {exact_price_matches} exact price matches"
            )
            score += 30  # Big boost when half or more items have exact price matches

        # CRITICAL REQUIREMENT: Must match a minimum percentage of items
        min_match_percentage = 60  # Need to match at least 60% of items
        if (
            order_items
            and (matched_count / len(order_items) * 100) < min_match_percentage
        ):
            score = 0  # Reset score if match percentage is too low
            print(
                f"[DEBUG] Score reset to 0 - matched only {matched_count}/{len(order_items)} items ({matched_count/len(order_items)*100:.1f}%)"
            )

        # If this quote has a better score than our current best match
        if score > best_score:
            best_score = score
            best_quote = quote
            matched_items = quote_matches
            print(
                f"[DEBUG] New best match: Quote #{quote.quote_number} with score {score:.1f}"
            )

        # INDUSTRIAL EQUIPMENT MATCHING
        # This handles cases where industrial equipment like flashback arrestors
        # have differently formatted descriptions but identical prices and quantities
        if unique_price_matches > 0 and len(order_items) > 0 and len(quote_items) > 0:
            print(f"[DEBUG] Attempting industrial equipment matching...")

            # Define key terms for industrial equipment categories
            industrial_categories = {
                "flashback": [
                    "arrestor",
                    "flash",
                    "regulator",
                    "torch",
                    "oxygen",
                    "acetylene",
                    "end",
                    "side",
                    "3/8",
                    "brass",
                ],
                "regulator": ["pressure", "flow", "control", "gas", "valve"],
                "torch": ["welding", "cutting", "tip", "nozzle"],
                "hose": ["pipe", "tube", "coupling", "connector", "fitting"],
            }

            # Track potential industrial matches
            industrial_matches = []
            matched_order_items = set()
            matched_quote_items = set()

            # Compare each order item against each quote item
            for order_item in order_items:
                order_desc = order_item.description.lower()
                order_price = float(order_item.selling_price or 0)
                order_qty = order_item.quantity

                # Skip items without prices or quantities
                if not order_price or not order_qty:
                    continue

                # Extract key terms from order description
                order_terms = set()
                order_categories = []

                # Find which categories this item belongs to
                for category, terms in industrial_categories.items():
                    if category in order_desc or any(
                        term in order_desc for term in terms
                    ):
                        order_categories.append(category)
                        order_terms.add(category)
                        for term in terms:
                            if term in order_desc:
                                order_terms.add(term)

                # Only proceed if we have enough identifying terms
                if len(order_terms) < 2:
                    continue

                print(f"[DEBUG] Order item '{order_desc}' has terms: {order_terms}")

                # Look for matching items in the quote
                for quote_item in quote_items:
                    # Skip already matched items
                    if quote_item in matched_quote_items:
                        continue

                    quote_desc = quote_item.description.lower()
                    quote_price = float(quote_item.selling_price or 0)
                    quote_qty = quote_item.quantity

                    # Skip items without prices or quantities
                    if not quote_price or not quote_qty:
                        continue

                    # Quick check: quantities and prices must match (within 1%)
                    if order_qty != quote_qty:
                        continue

                    if (
                        abs(order_price - quote_price) / max(order_price, quote_price)
                        > 0.01
                    ):
                        continue

                    # Extract key terms from quote description
                    quote_terms = set()
                    quote_categories = []

                    # Find which categories this item belongs to
                    for category, terms in industrial_categories.items():
                        if category in quote_desc or any(
                            term in quote_desc for term in terms
                        ):
                            quote_categories.append(category)
                            quote_terms.add(category)
                            for term in terms:
                                if term in quote_desc:
                                    quote_terms.add(term)

                    # Calculate term overlap
                    common_terms = order_terms.intersection(quote_terms)
                    term_overlap_percentage = len(common_terms) / max(
                        len(order_terms), len(quote_terms)
                    )

                    print(
                        f"[DEBUG] Comparing with quote item '{quote_desc}' - common terms: {common_terms}"
                    )

                    # Strong match if we have:
                    # 1. Same price
                    # 2. Same quantity
                    # 3. At least 2 common terms or 30% term overlap
                    if len(common_terms) >= 2 or term_overlap_percentage >= 0.3:
                        match_score = 70 + min(
                            len(common_terms) * 5, 25
                        )  # Base 70 + up to 25 more

                        industrial_matches.append(
                            {
                                "order_item": order_item,
                                "quote_item": quote_item,
                                "common_terms": list(common_terms),
                                "match_score": match_score,
                                "term_overlap": term_overlap_percentage,
                                "order_categories": order_categories,
                                "quote_categories": quote_categories,
                            }
                        )

                        print(
                            f"[DEBUG] Found industrial match with score {match_score}"
                        )
                        matched_order_items.add(order_item)
                        matched_quote_items.add(quote_item)
                        break  # We found a match for this order item

            # If we matched most items, consider this a good match
            if industrial_matches and len(industrial_matches) / len(order_items) >= 0.5:
                print(
                    f"[DEBUG] Strong industrial match! Matched {len(industrial_matches)}/{len(order_items)} items"
                )

                # Calculate overall score based on number of matches
                match_percentage = len(industrial_matches) / len(order_items)
                match_confidence = 65 + int(match_percentage * 25)

                # Create match details for display
                quote_matches = []
                for match in industrial_matches:
                    quote_matches.append(
                        {
                            "order_id": match["order_item"].id,
                            "order_desc": match["order_item"].description.lower(),
                            "quote_desc": match["quote_item"].description.lower(),
                            "match_score": match["match_score"],
                            "match_reason": f"Industrial match ({len(match['common_terms'])} shared terms)",
                            "quantity": match["quote_item"].quantity,
                            "order_quantity": match["order_item"].quantity,
                            "quote_price": float(match["quote_item"].selling_price),
                            "order_price": float(match["order_item"].selling_price),
                            "common_terms": match["common_terms"],
                            "order_categories": match["order_categories"],
                            "quote_categories": match["quote_categories"],
                            "matched_on": "industrial_terms",
                            "order_sizes": [],
                            "quote_sizes": [],
                            "supplier_match": False,
                        }
                    )

                # For logging - what did we match?
                for match in quote_matches:
                    print(
                        f"[DEBUG] Matched: '{match['order_desc']}' → '{match['quote_desc']}'"
                    )
                    print(f"[DEBUG]   Common terms: {match['common_terms']}")

                # Update best match if this is better
                if match_confidence > best_score:
                    print(
                        f"[DEBUG] UPDATED best match: Quote #{quote.quote_number} with score {match_confidence}"
                    )
                    best_score = match_confidence
                    best_quote = quote
                    matched_items = quote_matches
                    matched_count = len(industrial_matches)

                continue  # Done with this quote

    # Store matching information for display
    if best_quote:
        cache_key = f"order_{order.id}_matched_items"
        cache.set(cache_key, json.dumps(matched_items), 3600)  # Cache for 1 hour

    # THRESHOLDS - make automatic matches harder to achieve
    if best_score >= 70 and best_quote:  # Raised from 60 to 70
        order.quote = best_quote
        order.quote_match_confidence = best_score
        order.quote_matching_attempted = True
        order.save(
            update_fields=[
                "quote",
                "quote_match_confidence",
                "quote_matching_attempted",
            ]
        )
        print(f"[DEBUG] Automatic match found! Score: {best_score:.1f}")
        return True, best_quote, best_score

    # Store potential match if below threshold but above minimum confidence
    elif best_quote and best_score >= 40:  # 40-69% range (raised from 30-59%)
        order.potential_quote = best_quote
        order.potential_quote_confidence = best_score
        order.quote_matching_attempted = True
        order.save(
            update_fields=[
                "potential_quote",
                "potential_quote_confidence",
                "quote_matching_attempted",
            ]
        )
        print(f"[DEBUG] Potential match found. Score: {best_score:.1f}")
        return False, best_quote, best_score

    # Mark that we attempted matching, even if unsuccessful
    order.quote_matching_attempted = True
    order.save(update_fields=["quote_matching_attempted"])
    print("[DEBUG] No good matches found")

    # Return suggested quote even if below confidence threshold
    if best_quote and best_score > 25:
        return False, best_quote, best_score

    return False, None, 0


def find_potential_duplicate_orders(new_order_data):
    """
    Find potential duplicate orders based on company and order items.
    Returns a list of potential duplicates with confidence scores.
    """
    from django.db.models import Q
    from .models import Order, OrderItem
    import difflib
    from datetime import timedelta
    from django.utils import timezone

    company_id = new_order_data.get("company")
    descriptions = new_order_data.get("description", [])

    if not company_id or not descriptions:
        return []

    # Find orders from the same company in the last 30 days
    recent_orders = Order.objects.filter(
        company_id=company_id, created_at__gte=timezone.now() - timedelta(days=30)
    ).prefetch_related("items")

    potential_duplicates = []

    for order in recent_orders:
        # Skip if exactly same order number and not empty
        if (
            order.order_number
            and new_order_data.get("order_number")
            and order.order_number == new_order_data.get("order_number")
        ):
            continue

        # Get items for this order
        order_items = list(order.items.all())

        # Skip if item count is very different
        if abs(len(order_items) - len(descriptions)) > max(3, len(descriptions) // 2):
            continue

        # Compare items
        matching_items = []
        match_score = 0

        for i, new_desc in enumerate(descriptions):
            if not new_desc.strip():
                continue

            best_match = None
            best_match_score = 0

            for order_item in order_items:
                # Check similarity
                similarity = difflib.SequenceMatcher(
                    None, new_desc.lower(), order_item.description.lower()
                ).ratio()

                if similarity > best_match_score:
                    best_match_score = similarity
                    best_match = order_item

            # If we found a good match
            if best_match_score > 0.6:
                match_score += best_match_score * 100

                # Get quantity if available
                try:
                    if i < len(new_order_data.get("quantity", [])):
                        new_qty = int(new_order_data["quantity"][i])
                    else:
                        new_qty = 1
                except (ValueError, TypeError):
                    new_qty = 1

                matching_items.append(
                    {
                        "new_desc": new_desc,
                        "new_qty": new_qty,
                        "match_desc": best_match.description,
                        "match_qty": best_match.quantity,
                        "similarity": best_match_score,
                    }
                )

        # Only include if we have some matches
        if matching_items:
            # Calculate match percentage
            match_percentage = (len(matching_items) / len(descriptions)) * 100

            # Calculate days ago
            days_ago = (timezone.now() - order.created_at).days

            # Calculate final score (weighted average of match score and recency)
            final_score = (match_score / len(descriptions)) * 0.8 + (
                30 - min(days_ago, 30)
            ) * 0.7

            potential_duplicates.append(
                {
                    "order": order,
                    "score": final_score,
                    "match_percentage": match_percentage,
                    "days_ago": days_ago,
                    "matching_items": matching_items,
                }
            )

    # Sort by score (highest first)
    potential_duplicates.sort(key=lambda x: x["score"], reverse=True)

    # Limit results
    return potential_duplicates[:5]
