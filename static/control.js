"use strict";

jQuery(() => {
    (($) => {
        $.new = (elementType) => {
            return $(document.createElement(elementType));
        };

        // WebSocket creation, using the hostname from the GUI
        let webSocket = null;
        // Main wrapper element for all buttons
        const ptzWrapper = $("#ptz-wrapper");
        const waitText = $("#wait-text");
        // Map of header elements
        const ptzHeaders = {};
        // References for Bootstrap Modal for label and color
        const labelModal = $("#label-modal");
        const bsLabelModal = new bootstrap.Modal(labelModal.get(0));
        const labelModalSave = $("#label-modal-save");
        const labelModalSaveSet = $("#label-modal-save-set");
        const labelInput = $("#label-input");
        // Create the column div for one PTZ camera
        const makePtzCol = (index, ip, tallyState) => {
            const header = $
                .new("h1")
                .text("PTZ " + (index + 1));
            ptzHeaders[index] = header;
            updatePtzHeader(index, tallyState);
            const col = $
                .new("div")
                .attr("class", "col px-4")
                .append(header)
                .append($.new("h2").text(ip))
                .appendTo(ptzWrapper);
            return $
                .new("div")
                .attr("class", "row")
                .appendTo(col);
        };
        // Update PTZ header with tally state
        const updatePtzHeader = (index, state) => {
            const TALLY_CLASSES = {
                0: "",  // Inactive
                1: "btn-success",  // Preview
                2: "btn-danger",  // Program
                3: "btn-danger"  // Preview & Program
            };
            const header = ptzHeaders[index];
            header.attr("class", TALLY_CLASSES[state]);
        };
        // Create one button from the row data
        const makePtzButton = (row) => {
            return $
                .new("div")
                .attr("class", "col-12 col-lg-6 col-xxl-4 p-2")
                .append($
                    .new("button")
                    .attr({
                        "type": "button",
                        "id": "button-" + row["cam"] + "-" + row["pos"],
                        "class": "btn btn-lg ptz-button shadow-none " + row["btn_class"]
                    })
                    .text(row["name"])
                    .data(row));
        };
        // Update button, finding it in DOM if neccessary
        const updateButton = (data, button) => {
            if (button === undefined) {
                button = $("#button-" + data["cam"] + "-" + data["pos"]);
            }
            const oldClass = button.data("btn_class");
            // noinspection JSVoidFunctionReturnValueUsed
            data = $.extend(button.data(), data);
            button
                .data(data)
                .removeClass(oldClass)
                .addClass(data["btn_class"])
                .text(data["name"]);
            return data;
        };
        // Send over WebSocket
        const wsSend = (eventName, data) => {
            webSocket.send(JSON.stringify({
                "event": eventName,
                "data": data
            }));
        };
        const sendOnOff = (value, event) => {
            if (value === "on") {
                wsSend(event, true);
            } else if (value === "off") {
                wsSend(event, false);
            } else {
                console.error("WTF is this?");
            }
        };
        // Functions for signaling and saving
        const body = $(document.body);
        const flashBackground = (animation, durationMs) => {
            if (durationMs === undefined) {
                durationMs = 500;
            }
            body.css("animation", animation + " " + (durationMs/1000).toFixed(3) + "s ease-in-out")
            setTimeout(() => body.css("animation", ""), durationMs);
        };
        const savePos = (data) => {
            wsSend("save_pos", {
                "cam": data["cam"],
                "pos": data["pos"]
            });
            flashBackground("pulse-green");
        };
        const updateOnAirChangeButtons = (allowOnAirChange) => {
            if (allowOnAirChange) {
                $("#on-air-change-on").prop("checked", true);
            } else {
                $("#on-air-change-off").prop("checked", true);
            }
        };

        // WebSocket message handling
        const wsMessageHandler = (message) => {
            const messageData = JSON.parse(message.data);
            const event = messageData.event;
            const data = messageData.data;
            console.log(event, data);
            switch (event) {
                case "init":
                    const cameraIps = data["camera_ips"];
                    const posData = data["all_pos"];
                    const tallyStates = data["tally_states"];
                    let cam = null;
                    let col = null;
                    waitText.hide();
                    // Remove all columns before repaint
                    waitText.nextAll().remove();
                    posData.forEach((row) => {
                        if (row["cam"] !== cam) {
                            cam = row["cam"];
                            col = makePtzCol(cam, cameraIps[cam], tallyStates[cam]);
                        }
                        col.append(makePtzButton(row));
                    });
                    updateOnAirChangeButtons(data["on_air_change_allowed"]);
                    break;
                case "update_button":
                    updateButton(data);
                    break;
                case "update_tally":
                    data.forEach((state, index) => updatePtzHeader(index, state));
                    break;
                case "update_on_air_change":
                    updateOnAirChangeButtons(data);
                    break;
                default:
                    console.log("Unknown event: " + event, data);
            }
        };
        let wsTimeout = null;
        const connectWebSocket = () => {
            wsTimeout = null;
            webSocket = new WebSocket("ws://" + window.location.hostname + "/ws");
            webSocket.onmessage = wsMessageHandler;
            const handleReconnect = (message, timeout) => {
                if (wsTimeout === null) {
                    waitText.show();
                    waitText.nextAll().remove();
                    console.log(message);
                    wsTimeout = setTimeout(connectWebSocket, timeout);
                }
            };
            webSocket.onclose = () => handleReconnect("Server connection closed, try reconnect...", 0);
            webSocket.onerror = () => handleReconnect("WebSocket error, try reconnect after 1 second delay...", 1000);
        };
        connectWebSocket();

        // Event handler for clear all
        $("#button-clear-all").click(() => {
            if (confirm("Are you sure you want to RESET ALL LABELS AND COLORS?")) {
                wsSend("clear_all", null);
            }
        });
        // Event handler for restart
        $("#button-reconnect").click(() => {
            wsSend("reconnect", null);
        });
        // Event handler for power
        $("#button-power-group").on("click", "button", (event) => {
            if (event.target.value !== "off" || confirm("Are you sure you want to TURN OFF ALL PTZ CAMERAS?")) {
                sendOnOff(event.target.value, "power")
            } else {
                event.preventDefault();
            }
        });
        // Event handler for on air change lock
        $("#button-on-air-change-group").on("click", "input", (event) => {
            window.localStorage.setItem("onAirChangeState", event.target.value);
            sendOnOff(event.target.value, "allow_on_air_change");
        });
        // Load persistent (client-side) On Air Change setting
        (() => {
            const onAirChangeState = window.localStorage.getItem("onAirChangeState") || "off";
            $("#button-on-air-change-group input[value=" + onAirChangeState + "]").click();
        })();
        // Event handler for focus lock
        $("#button-focus-lock-group").on("click", "button", 
            (event) => sendOnOff(event.target.value, "focus_lock"));
        // Button modes
        const RECALL = "mode_recall";
        const LABEL = "mode_label";
        // Current mode of buttons
        let buttonMode = RECALL;
        // Event handler for button modes
        $("#button-mode-group").on("change", "input", (event) => {
            buttonMode = event.target.value;
        });
        // Menu wrapper buttons active state fix
        $("#menu-wrapper").on("click", "button", (event) => {
            $(event.target).blur();
        });
        // Page-global event handler for modes
        $(document).keyup((event) => {
            if (event.ctrlKey || event.altKey) {
                console.log(event.key);
                switch (event.key) {
                    case "r": case "R": case "ArrowLeft":
                        $("#mode-recall").click();
                        break;
                    case "l": case "L": case "ArrowRight":
                        $("#mode-label").click();
                        break;
                }
                event.preventDefault();
            }
        });

        // On Air Change on button
        const onAirChangeOnButton = $("#on-air-change-on");
        // Last button clicked
        let downButton = null;
        let downTimeout = null;
        // Button listeners, using pointer events
        ptzWrapper.on("pointerdown", ".ptz-button", (event) => {
            // Prevent button state change on click/touch
            event.preventDefault();
            // Filter for left click or direct touch/pen contact, see
            // https://www.w3.org/TR/pointerevents3/#the-button-property
            if (event.button !== undefined && event.button !== 0) {
                return;
            }
            downButton = $(event.target);
            downTimeout = setTimeout(() => {
                savePos(downButton.data());
                downTimeout = null;
            }, 1000);
        });
        ptzWrapper.on("pointerleave", ".ptz-button", () => {
            if (downTimeout !== null) {
                console.log("Pointer left button, abort action.");
                clearTimeout(downTimeout);
                downTimeout = null;
            }
        });
        ptzWrapper.on("pointerup", ".ptz-button", (event) => {
            if (downTimeout !== null) {
                clearTimeout(downTimeout);
                downTimeout = null;
                if (downButton.get(0) !== event.target) {
                    console.log("Changed button before pointerup event, ignoring.");
                    return;
                }
                const data = downButton.data();
                switch (buttonMode) {
                    case RECALL:
                        const ptzHeader = ptzHeaders[data["cam"]];
                        if ((ptzHeader.hasClass("btn-danger") || ptzHeader.hasClass("btn-warning"))
                            && !onAirChangeOnButton.is(":checked")
                        ) {
                            flashBackground("pulse-red", 300);
                        } else {
                            wsSend("recall_pos", {
                                "cam": data["cam"],
                                "pos": data["pos"]
                            });
                        }
                        break;
                    case LABEL:
                        $("#btn-class-radios input")
                            .filter((_index, element) => element.value === data["btn_class"])
                            .prop("checked", true);
                        bsLabelModal.show();
                        labelInput.val(data["name"]);
                        break;
                }
            }
        });
        // Filter contextmenu event
        $(document).on("contextmenu", ".ptz-button", (event) => event.preventDefault());
        // Modal event listeners
        labelModal.keyup((event) => {
            if (event.key === "Enter") {
                if (event.ctrlKey || event.altKey) {
                    labelModalSaveSet.click();
                } else {
                    labelModalSave.click();
                }
            }
        });
        labelModal.on("shown.bs.modal", () => {
            labelInput.focus();
            labelInput.get(0).setSelectionRange(0, labelInput.val().length)
        });
        labelModalSave.click(() => {
            const newData = updateButton({
                "name": labelInput.val(),
                "btn_class": $("#btn-class-radios input:checked").val()
            }, downButton);
            wsSend("update_button", newData);
            downButton = null;
            bsLabelModal.hide();
        });
        labelModalSaveSet.click(() => {
            const data = downButton.data();
            labelModal.one("hidden.bs.modal", () => savePos(data));
            labelModalSave.click();
        });
    })(jQuery);
});