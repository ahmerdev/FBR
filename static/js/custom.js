$(document).ready(function () {
    const pageTitle = $('#titlePage').text();
    if (pageTitle) {
        document.title = `Dashboard | ${pageTitle}`;
    }

    const fullURL = window.location.href;
    const origin = window.location.origin;
    const links = $(".sidebar-nav a");
    let matched = false;
    let checkedURLs = [];

    links.each(function () {
        const href = $(this).attr("href");

        // Skip empty or javascript:void(0) links
        if (!href || href.startsWith("javascript")) return;

        const checkURL = new URL(href, origin).href;
        checkedURLs.push(checkURL);

        if (checkURL === fullURL) {
            $(this).closest(".sidebar-item").addClass("active");
            matched = true;
            return false; // Break out of .each() loop
        }
    });

    if (!matched) {
        console.log("No match found for URL:");
        console.log("Current URL: ", fullURL);
        console.log("Checked URLs: ", checkedURLs);
    }

    $(".click-drop").click(function () {
        l = $(this).closest('.sidebar-item').find('.m_i').toggleClass('d-block');
    });

    if (document.getElementById('password')) {
        $('#password').val('')
    }
});

document.addEventListener('DOMContentLoaded', function () {
    const passwordInput = document.getElementById('password');
    const togglePassword = document.getElementById('toggle-password');
    const strengthFill = document.getElementById('strength-fill');
    const strengthText = document.getElementById('strength-text');
    const lengthReq = document.getElementById('length');
    const uppercaseReq = document.getElementById('uppercase');
    const lowercaseReq = document.getElementById('lowercase');
    const numberReq = document.getElementById('number');
    const specialReq = document.getElementById('special');

    // Toggle password visibility
    if (togglePassword) {
        togglePassword.addEventListener('click', function () {
            const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
            passwordInput.setAttribute('type', type);

            // Toggle eye icon
            const icon = togglePassword.querySelector('i');
            icon.classList.toggle('fa-eye');
            icon.classList.toggle('fa-eye-slash');
        });

        // Check password strength on input
        passwordInput.addEventListener('input', function () {
            const password = passwordInput.value;
            const container = passwordInput.closest('.password-strength-container');

            // Remove all strength classes
            container.classList.remove(
                'strength-very-weak',
                'strength-weak',
                'strength-medium',
                'strength-strong',
                'strength-very-strong'
            );

            // Check requirements
            const hasLength = password.length >= 8;
            const hasUppercase = /[A-Z]/.test(password);
            const hasLowercase = /[a-z]/.test(password);
            const hasNumber = /[0-9]/.test(password);
            const hasSpecial = /[^A-Za-z0-9]/.test(password);

            // Update requirement status
            updateRequirement(lengthReq, hasLength);
            updateRequirement(uppercaseReq, hasUppercase);
            updateRequirement(lowercaseReq, hasLowercase);
            updateRequirement(numberReq, hasNumber);
            updateRequirement(specialReq, hasSpecial);

            // Calculate strength score (0-5)
            let strengthScore = 0;
            if (password.length > 0) strengthScore += 1;
            if (hasLength) strengthScore += 1;
            if (hasUppercase) strengthScore += 1;
            if (hasLowercase) strengthScore += 1;
            if (hasNumber) strengthScore += 1;
            if (hasSpecial) strengthScore += 1;

            // Adjust score to max of 5
            strengthScore = Math.min(5, Math.floor(strengthScore * 5 / 6));

            // Update strength meter and text
            updateStrengthMeter(container, strengthScore, strengthText);
        });

        function updateRequirement(element, isValid) {
            const icon = element.querySelector('i');

            if (isValid) {
                element.classList.add('valid');
                icon.classList.remove('fa-times-circle');
                icon.classList.add('fa-check-circle');
            } else {
                element.classList.remove('valid');
                icon.classList.remove('fa-check-circle');
                icon.classList.add('fa-times-circle');
            }
        }

        function updateStrengthMeter(container, score, textElement) {
            const strengthClasses = [
                '',
                'strength-very-weak',
                'strength-weak',
                'strength-medium',
                'strength-strong',
                'strength-very-strong'
            ];

            const strengthTexts = [
                'Enter a password',
                'Very weak',
                'Weak',
                'Medium',
                'Strong',
                'Very strong'
            ];

            // Add appropriate class
            if (score > 0) {
                container.classList.add(strengthClasses[score]);
            }

            // Update text
            textElement.textContent = strengthTexts[score];
        }
    }

    if (document.getElementById('msg-toast')) {
        setTimeout(fn => {
            $('#msg-toast').toggleClass('d-block')
        }, 3000)
    }
});




var pasMatch = false;
$('#confirm_password').keyup(function () {
    let v = this.value;
    let cv = $('#password').val();
    if (v == cv) {
        pasMatch = true;
        $('#ismatch').html('<span class="text-success">Passwords matched</span>')
    }
    else {
        pasMatch = false;
        $('#ismatch').html('<span class="text-danger">Passwords Un-matched</span>')
    }
})

$("#ValidateForm").submit(function (e) {
    e.preventDefault(); // stop form submission by default
    $("#form_validate").text('');
    let uid = Number($("#uid").val());
    let chP = $('#password').val();
    if (pasMatch || (uid != 0 && !chP)) {
        let u = $('#username').val()
        if (u) {
            $.ajax({
                url: `/dashboard/check-username?username=${u}&uid=${uid}`,
                type: 'get',
                success: function (data) {
                    console.log(data)
                    if (data == 'True') {
                        $("#form_validate").text('Email address already taken');
                        return;
                    }
                    else {
                        $("#ValidateForm")[0].submit();
                    }
                    return;
                },
                error: function (err) {
                    $("#form_validate").text('Unable to submit form');
                    console.log(err)
                    return;
                }
            });
        }
        else {
            $("#form_validate").text('Please enter email address');
            return;
        }
    }
    else {
        $("#form_validate").text('Passwords are not matched');
        return false;
    }
})
window.onload = function () {
    $('.deleteToggle').click(function () {
        $('#deleteRec').attr('href', $(this).data('href'))
        const modal = new bootstrap.Modal(document.getElementById('DeleteModal'));
        modal.show();
    })
    $('.toggleEnv').click(function () {
        const modal = new bootstrap.Modal(document.getElementById('envStatus'));
        modal.show();
    })
    $('.datatable').each(function () {
        const table = $(this);
        const tableName = table.data('name') || 'exported-file'; // fallback if no data-name

        table.DataTable({
            columnDefs: [
                { orderable: false, targets: "no-sort" }
            ],
            dom: 'fBrtlp',
            buttons: [
                {
                    extend: 'csv',
                    filename: tableName,
                    exportOptions: {
                        columns: ':not(.no-export)'
                    }
                },
                {
                    extend: 'pdf',
                    filename: tableName,
                    exportOptions: {
                        columns: ':not(.no-export)'
                    }
                }
            ]
        });
    });
    $("#loader").toggleClass('d-none');
    $("#maincontent").toggleClass('d-none');
};